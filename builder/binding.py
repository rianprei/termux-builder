import os
import xml.etree.ElementTree as ET
from builder.utils import ensure_dir, log


def generate(config):
    if not config.view_binding:
        return

    log.info("Generating ViewBinding classes")
    layouts_dir = os.path.join(config.res_dir, "layout")
    if not os.path.isdir(layouts_dir):
        log.warning("No layout directory found — skipping ViewBinding")
        return

    for f in os.listdir(layouts_dir):
        if not f.endswith(".xml"):
            continue
        layout_path = os.path.join(layouts_dir, f)
        _generate_binding_class(config, layout_path)


def _generate_binding_class(config, layout_path):
    filename = os.path.basename(layout_path).replace(".xml", "")
    class_name = _to_pascal_case(filename) + "Binding"

    try:
        tree = ET.parse(layout_path)
    except ET.ParseError:
        log.warning("Failed to parse layout: %s", layout_path)
        return

    root = tree.getroot()
    views = _collect_views(root)

    pkg_path = config.package_name.replace(".", os.sep)
    out_dir = ensure_dir(os.path.join(config.binding_dir, pkg_path, "databinding"))
    out_file = os.path.join(out_dir, f"{class_name}.java")

    pkg = config.package_name
    r_class = f"{pkg}.R"

    lines = [
        f"package {pkg}.databinding;",
        "",
        "import android.view.LayoutInflater;",
        "import android.view.View;",
        "import android.view.ViewGroup;",
        f"import {r_class};",
        "",
        f"public final class {class_name} {{",
        "    private final View rootView;",
    ]

    for view_id, view_type in views:
        field_name = _to_camel_case(view_id)
        lines.append(f"    public final {view_type} {field_name};")

    lines += [
        "",
        f"    private {class_name}(View rootView) {{",
        "        this.rootView = rootView;",
    ]

    for view_id, view_type in views:
        field_name = _to_camel_case(view_id)
        lines.append(
            f"        this.{field_name} = ({view_type}) rootView.findViewById(R.id.{view_id});"
        )

    lines += [
        "    }",
        "",
        "    public View getRoot() { return rootView; }",
        "",
        f"    public static {class_name} inflate(LayoutInflater inflater) {{",
        f"        View root = inflater.inflate(R.layout.{filename}, null);",
        f"        return new {class_name}(root);",
        "    }",
        "",
        f"    public static {class_name} inflate(LayoutInflater inflater, ViewGroup parent, boolean attach) {{",
        f"        View root = inflater.inflate(R.layout.{filename}, parent, attach);",
        f"        return new {class_name}(root);",
        "    }",
        "}",
    ]

    with open(out_file, "w") as f:
        f.write("\n".join(lines) + "\n")


def _collect_views(element, views=None):
    if views is None:
        views = []

    view_id = element.attrib.get("{http://schemas.android.com/apk/res/android}id", "")
    if view_id.startswith("@+id/") or view_id.startswith("@id/"):
        clean_id = view_id.split("/", 1)[1]
        tag = element.tag
        if "." in tag:
            view_type = tag
        else:
            view_type = f"android.widget.{tag}" if tag[0].isupper() else "android.view.View"
        views.append((clean_id, view_type))

    for child in element:
        _collect_views(child, views)

    return views


def _to_pascal_case(snake):
    return "".join(w.capitalize() for w in snake.split("_"))


def _to_camel_case(snake):
    parts = snake.split("_")
    return parts[0] + "".join(w.capitalize() for w in parts[1:])
