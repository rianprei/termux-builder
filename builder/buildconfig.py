import os
from builder.utils import ensure_dir, log


def generate(config):
    log.info("Generating BuildConfig.java")
    pkg_path = config.package_name.replace(".", os.sep)
    out_dir = ensure_dir(os.path.join(config.gen_dir, pkg_path))
    out_file = os.path.join(out_dir, "BuildConfig.java")

    is_debug = "true" if config.build_type == "debug" else "false"

    content = f"""package {config.package_name};

public final class BuildConfig {{
    public static final boolean DEBUG = {is_debug};
    public static final String APPLICATION_ID = "{config.package_name}";
    public static final String BUILD_TYPE = "{config.build_type}";
    public static final int VERSION_CODE = {config.version_code};
    public static final String VERSION_NAME = "{config.version_name}";
    public static final int MIN_SDK_VERSION = {config.min_sdk};
    public static final int TARGET_SDK_VERSION = {config.target_sdk};
}}
"""
    with open(out_file, "w") as f:
        f.write(content)
