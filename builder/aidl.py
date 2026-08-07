import os
from builder.utils import run, find_files, find_bin, ensure_dir, log


def compile(config):
    aidl_dir = os.path.join(config.sources_dir)
    aidl_files = find_files(aidl_dir, ".aidl")
    if not aidl_files:
        return

    aidl_bin = find_bin("aidl")
    if not aidl_bin:
        log.warning("aidl not found in PATH — skipping AIDL compilation")
        return

    log.info("Compiling %d AIDL files", len(aidl_files))
    out_dir = ensure_dir(os.path.join(config.gen_dir, "aidl"))

    framework_aidl = os.path.join(
        config.sdk_dir, "platforms", f"android-{config.target_sdk}", "framework.aidl"
    )

    for aidl_file in aidl_files:
        args = [aidl_bin]
        if os.path.isfile(framework_aidl):
            args += ["-p", framework_aidl]
        args += [
            "-I", aidl_dir,
            "-o", out_dir,
            aidl_file,
        ]
        run(args)

    config._aidl_gen_dir = out_dir
