import os
from builder.utils import run, log


def sign(config):
    unsigned = os.path.join(config.bin_dir, "unsigned.apk")
    output_name = f"{config.name}-{config.build_type}.apk"
    signed = os.path.join(config.build_dir, output_name)

    log.info("Signing APK")

    if not os.path.isfile(config.keystore_path):
        raise FileNotFoundError(f"Keystore not found: {config.keystore_path}")

    run([
        config.bin_apksigner, "sign",
        "--ks", config.keystore_path,
        "--ks-key-alias", config.keystore_alias,
        "--ks-pass", f"pass:{config.keystore_store_pass}",
        "--key-pass", f"pass:{config.keystore_key_pass}",
        "--out", signed,
        "--in", unsigned,
    ])

    os.remove(unsigned)
    size_mb = os.path.getsize(signed) / (1024 * 1024)
    log.info("Signed APK: %s (%.1f MB)", signed, size_mb)
    return signed


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
