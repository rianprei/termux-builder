import os
import tempfile
from builder.utils import ensure_output_path, run, log, variant_name


def sign(config, abi=None):
    unsigned = os.path.join(config.bin_dir, f"unsigned-{abi}.apk" if abi else "unsigned.apk")
    name = variant_name(config)
    output_name = f"{name}-{abi}-{config.build_type}.apk" if abi else f"{name}-{config.build_type}.apk"
    signed = os.path.join(config.build_dir, output_name)
    result = sign_apk(config, unsigned, signed)
    os.remove(unsigned)
    return result


def _publish_signed_outputs(
    staging_path, staging_idsig_path, signed_path, signed_idsig_path, sign_v4
):
    directory = os.path.dirname(signed_path)
    backup_path = None
    backup_idsig_path = None
    apk_backed_up = False
    idsig_backed_up = False
    apk_published = False
    idsig_published = False
    publication_succeeded = False
    try:
        if os.path.lexists(signed_path):
            fd, backup_path = tempfile.mkstemp(prefix=".previous-", suffix=".apk", dir=directory)
            os.close(fd)
            os.replace(signed_path, backup_path)
            apk_backed_up = True
        if os.path.lexists(signed_idsig_path):
            fd, backup_idsig_path = tempfile.mkstemp(
                prefix=".previous-", suffix=".idsig", dir=directory
            )
            os.close(fd)
            os.replace(signed_idsig_path, backup_idsig_path)
            idsig_backed_up = True

        os.replace(staging_path, signed_path)
        apk_published = True
        if sign_v4:
            os.replace(staging_idsig_path, signed_idsig_path)
            idsig_published = True
        publication_succeeded = True
    except BaseException as publication_error:
        # A signal can arrive after rename succeeds but before its state flag is set.
        if backup_path and not os.path.lexists(signed_path) and os.path.lexists(backup_path):
            apk_backed_up = True
        if (
            backup_idsig_path
            and not os.path.lexists(signed_idsig_path)
            and os.path.lexists(backup_idsig_path)
        ):
            idsig_backed_up = True
        if not os.path.lexists(staging_path) and os.path.lexists(signed_path):
            apk_published = True
        if sign_v4 and not os.path.lexists(staging_idsig_path) and os.path.lexists(signed_idsig_path):
            idsig_published = True

        rollback_errors = []
        if idsig_backed_up:
            try:
                os.replace(backup_idsig_path, signed_idsig_path)
                backup_idsig_path = None
                idsig_backed_up = False
            except BaseException as error:
                if not os.path.lexists(backup_idsig_path) and os.path.lexists(signed_idsig_path):
                    backup_idsig_path = None
                    idsig_backed_up = False
                else:
                    rollback_errors.append(f"{error} (backup: {backup_idsig_path})")
        elif idsig_published and os.path.lexists(signed_idsig_path):
            try:
                os.unlink(signed_idsig_path)
            except BaseException as error:
                if os.path.lexists(signed_idsig_path):
                    rollback_errors.append(f"{error} (output: {signed_idsig_path})")
        if apk_backed_up:
            try:
                os.replace(backup_path, signed_path)
                backup_path = None
                apk_backed_up = False
            except BaseException as error:
                if not os.path.lexists(backup_path) and os.path.lexists(signed_path):
                    backup_path = None
                    apk_backed_up = False
                else:
                    rollback_errors.append(f"{error} (backup: {backup_path})")
        elif apk_published and os.path.lexists(signed_path):
            try:
                os.unlink(signed_path)
            except BaseException as error:
                if os.path.lexists(signed_path):
                    rollback_errors.append(f"{error} (output: {signed_path})")
        if rollback_errors:
            recovery_paths = [
                path for path in (backup_path, backup_idsig_path)
                if path and os.path.lexists(path)
            ]
            recovery = ", ".join(recovery_paths) or f"{signed_path} and {signed_idsig_path}"
            raise RuntimeError(
                "APK output publication failed and rollback was incomplete; "
                f"inspect or recover: {recovery}; "
                f"rollback errors: {'; '.join(rollback_errors)}"
            ) from publication_error
        raise
    finally:
        if publication_succeeded:
            for backup in (backup_path, backup_idsig_path):
                if backup and os.path.lexists(backup):
                    try:
                        os.unlink(backup)
                    except OSError as error:
                        log.warning(
                            "Unable to remove temporary signing backup %s: %s",
                            os.path.basename(backup), error,
                        )
        else:
            for backup, backed_up in (
                (backup_path, apk_backed_up),
                (backup_idsig_path, idsig_backed_up),
            ):
                if backup and not backed_up and os.path.lexists(backup):
                    os.unlink(backup)


def sign_apk(config, unsigned_path, signed_path):
    """Sign an arbitrary APK (base or density split) with the project keystore."""
    log.info("Signing APK: %s", os.path.basename(signed_path))

    build_dir = getattr(config, "build_dir", os.path.dirname(signed_path))
    ensure_output_path(build_dir, unsigned_path, "Unsigned APK input")
    ensure_output_path(build_dir, signed_path, "Signed APK output")
    signed_idsig_path = signed_path + ".idsig"
    ensure_output_path(build_dir, signed_idsig_path, "APK v4 signature output")
    if os.path.lexists(signed_path) and not os.path.isfile(signed_path):
        raise RuntimeError(f"Invalid signed APK output path: {signed_path}")
    if os.path.lexists(signed_idsig_path) and not os.path.isfile(signed_idsig_path):
        raise RuntimeError(f"Invalid APK v4 signature output path: {signed_idsig_path}")
    sign_v4 = bool(getattr(config, "sign_v4", False))

    if not os.path.isfile(config.keystore_path):
        raise FileNotFoundError(f"Keystore not found: {config.keystore_path}")
    if not os.path.isfile(unsigned_path):
        raise FileNotFoundError(f"Unsigned APK not found: {unsigned_path}")

    # pass via env, not argv/pass: — avoids leak through ps/proc/cmdline and debug logs
    env = os.environ.copy()
    env["_TB_KS_PASS"] = config.keystore_store_pass
    env["_TB_KEY_PASS"] = config.keystore_key_pass

    fd, staging_path = tempfile.mkstemp(
        prefix=".signed-", suffix=".apk", dir=os.path.dirname(signed_path)
    )
    os.close(fd)
    staging_idsig_path = staging_path + ".idsig"
    try:
        run([
            config.bin_apksigner, "sign",
            "--ks", config.keystore_path,
            "--ks-key-alias", config.keystore_alias,
            "--ks-pass", "env:_TB_KS_PASS",
            "--key-pass", "env:_TB_KEY_PASS",
            "--v1-signing-enabled", str(config.sign_v1).lower(),
            "--v2-signing-enabled", str(config.sign_v2).lower(),
            "--v3-signing-enabled", str(config.sign_v3).lower(),
            "--v4-signing-enabled", str(config.sign_v4).lower(),
            "--out", staging_path,
            "--in", unsigned_path,
        ], env=env)
        if not os.path.isfile(staging_path) or os.path.getsize(staging_path) == 0:
            raise RuntimeError("apksigner reported success without producing a signed APK")
        if sign_v4 and (
            not os.path.isfile(staging_idsig_path)
            or os.path.getsize(staging_idsig_path) == 0
        ):
            raise RuntimeError(
                "apksigner reported success without producing the v4 signature sidecar"
            )
        verify_args = [config.bin_apksigner, "verify"]
        if sign_v4:
            verify_args.extend(["-v4-signature-file", staging_idsig_path])
        verify_args.append(staging_path)
        run(verify_args)
        _publish_signed_outputs(
            staging_path, staging_idsig_path, signed_path, signed_idsig_path, sign_v4
        )
    finally:
        if staging_path and os.path.lexists(staging_path):
            os.unlink(staging_path)
        if staging_idsig_path and os.path.lexists(staging_idsig_path):
            os.unlink(staging_idsig_path)

    size_bytes = os.path.getsize(signed_path)
    if size_bytes < 1024:
        size = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size = f"{size_bytes / 1024:.1f} KiB"
    else:
        size = f"{size_bytes / (1024 * 1024):.1f} MiB"
    log.info("Signed APK: %s (%s)", signed_path, size)
    return signed_path


def generate_debug_keystore(path):
    if os.path.isfile(path):
        return path

    log.info("Generating debug keystore")
    run([
        "keytool", "-genkeypair",
        "-keystore", path,
        "-storepass", "android",
        "-alias", "androiddebugkey",
        "-keypass", "android",
        "-keyalg", "RSA",
        "-keysize", "2048",
        "-validity", "10000",
        "-dname", "CN=Debug,O=Android,C=US",
    ])
    return path
