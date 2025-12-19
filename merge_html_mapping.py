import os
import re
import shutil
import copy
import json
from bs4 import BeautifulSoup

# -----------------------------------------------------------------------------
# CONSTANTS & CONFIGURATION
# -----------------------------------------------------------------------------

# The main path prefix requested
BASE_DIR = "AIST-PICA-R5/"

CHANGE_TYPE_STYLES = {
    "BREAKING":  ("#dc3545", "#ffffff"),
    "REMOVED":   ("#dc3545", "#ffffff"),
    "RENAMED":   ("#ffc107", "#212529"),
    "MOVED":     ("#ffc107", "#212529"),
    "MERGED":    ("#ffc107", "#212529"),
    "STRUCTURE": ("#ffc107", "#212529"),
    "NEW":       ("#28a745", "#ffffff"),
    "INFO":      ("#ffc107", "#212529"),
}

# Load config
config_path = os.path.join("config.json")
with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)

# Extract config variables
prev_guide_version = config["comparison"]["previous_version"]
curr_guide_version = config["comparison"]["current_version"]
folder_name_prev_guide = config["comparison"]["previous_folder"]
fsh_path = config["comparison"]["fsh_path"]
table_names = config["tables"]
tabs_names = config["tabs"]

print(f"Previous guide version: {prev_guide_version}")
print(f"Current guide version: {curr_guide_version}")
print(f"Previous guide folder name: {folder_name_prev_guide}")
print(f"FSH path: {fsh_path}")
print(f"Tables to update: {table_names}")
print(f"Tabs to update: {tabs_names}")


# -----------------------------------------------------------------------------
# HELPER FUNCTIONS: File System & Profiles
# -----------------------------------------------------------------------------

def find_fsh(outpath):
    """Recursively finds .fsh files."""
    fsh = [file for file in os.listdir(outpath) if file.lower().endswith(".fsh")]
    subfolders = [f.name for f in os.scandir(outpath) if f.is_dir()]
    for folder in subfolders:
        sub_fsh = find_fsh(outpath + "/" + folder)
        fsh.extend([str(folder) + "/" + str(x) for x in sub_fsh])
    return fsh

def get_profile_ids(file_content):
    return re.findall(r'Id:\s*([\w\-_]*)', file_content)

def get_profile_ids_from_file_list(file_names, path_to_dir=""):
    """
    Extracts Profile Ids from a list of FSH files.
    path_to_dir: prefix path to the root containing the FSH folder.
    """
    ids = set()
    for fsh_file in file_names:
        # path construction: {path_to_dir}/{fsh_path}/{fsh_file}
        # Note: We handle the trailing slash logic carefully below
        full_path = os.path.join(path_to_dir, fsh_path, fsh_file)
        
        try:
            with open(full_path, mode="r", encoding="utf-8") as f:
                content = f.read()
                extracted = get_profile_ids(content)
                print(f"From {fsh_file} extracted {extracted}")
                ids.update(extracted)
        except FileNotFoundError:
            print(f"Warning: File not found: {full_path}")
            
    return ids

# -----------------------------------------------------------------------------
# HELPER FUNCTIONS: HTML Parsing & Manipulation
# -----------------------------------------------------------------------------

def add_max_width(element):
    """
    Adds a maximum width and ensures normal line breaks (white-space: normal) 
    for all table cells (td) to prevent content overflow.
    """
    all_rows = element.find_all("td")
    for row in all_rows:
        style = row.get("style", "")
        
        if "max-width" not in style:
            style += "; max-width: 150px"
        
        if "white-space" in style and "nowrap" in style:
            style = style.replace("nowrap", "normal")
            
        row["style"] = style.strip("; ")

def rewrite_ids(block, prefix):
    """
    Rewrites all element IDs, anchor names, and JavaScript references
    by adding a PREFIX in front of existing identifiers.
    """
    id_map = {}

    # Update all element IDs
    for tag in block.find_all(id=True):
        original_id = tag["id"]
        new_id = prefix + original_id
        id_map[original_id] = new_id
        tag["id"] = new_id

    # Update anchor names 
    for tag in block.find_all("a", attrs={"name": True}):
        original_name = tag["name"]
        new_name = prefix + original_name
        id_map[original_name] = new_name
        tag["name"] = new_name

    # Update inline JavaScript event handlers
    tags_with_js = block.find_all(
        lambda tag: any(attr.startswith("on") for attr in tag.attrs)
    )

    def update_handler(handler):
        if not handler:
            return handler

        # Ensure case-insensitive comparisons for input values
        value_patterns = [
            r'(this\.value)\s*(?![.]?toLowerCase)',
            r'(event\.target\.value)\s*(?![.]?toLowerCase)'
        ]
        for pattern in value_patterns:
            handler = re.sub(pattern, r'\1.toLowerCase()', handler)

        # Replace IDs
        for original_id, new_id in id_map.items():
            handler = handler.replace(f"'{original_id}'", f"'{new_id}'")
            handler = handler.replace(f"\"{original_id}\"", f"\"{new_id}\"")
            handler = handler.replace(f" {original_id} ", f" {new_id} ")

        return handler

    for tag in tags_with_js:
        for attr in tag.attrs:
            if attr.startswith("on"):
                tag[attr] = update_handler(tag[attr])

    # Update internal anchor links
    for a in block.find_all("a", href=True):
        href = a["href"]
        if href.startswith("#") and len(href) > 1:
            original_anchor = href[1:]
            if original_anchor in id_map:
                a["href"] = f"#{prefix}{original_anchor}"

# -----------------------------------------------------------------------------
# HELPER FUNCTIONS: Merging Logic
# -----------------------------------------------------------------------------

def merge_tables(prev, curr):
    """
    Merges HTML tables (tbl-key, tbl-diff etc.) from the previous and current versions.
    """
    for table_name in table_names:
        prev_table = prev.find("div", {"id": table_name})
        curr_table = curr.find("div", {"id": table_name})
        
        if prev_table is None or curr_table is None:
            if prev_table is None and curr_table is None:
                continue
            print(f"Warning: Table '{table_name}' missing in one version. Skipping merge.")
            continue

        prev_copy = copy.deepcopy(prev_table)
        curr_copy = copy.deepcopy(curr_table)

        add_max_width(prev_copy)
        add_max_width(curr_copy)
        
        rewrite_ids(prev_copy, "prev-")
        rewrite_ids(curr_copy, "curr-")

        prev_wrapper = curr.new_tag("div", **{"class": "prev-container"})
        prev_wrapper.append(prev_copy)
        curr_wrapper = curr.new_tag("div", **{"class": "curr-container"})
        curr_wrapper.append(curr_copy)
        
        merged_html = f"""
        <div class="row no-gutters merged-table-container" style="border: 1px solid #DEE2E6; border-radius: 4px; margin-top: 15px;">
            <div class="col-6" style="padding: 15px; background-color: #F8F9FA;">
                <h4 style="color: #333; border-bottom: 1px solid #DEE2E6; padding-bottom: 5px; margin-bottom: 15px; font-weight: 600;">Version: {prev_guide_version}</h4>
                {str(prev_wrapper)}
            </div>
            <div class="col-6" style="padding: 15px; border-left: 1px solid #DEE2E6; background-color: #FFFFFF;">
                <h4 style="color: #333; border-bottom: 1px solid #DEE2E6; padding-bottom: 5px; margin-bottom: 15px; font-weight: 600;">Version: {curr_guide_version}</h4>
                {str(curr_wrapper)}
            </div>
        </div>
        """
        
        merged_fragment = BeautifulSoup(merged_html, "html.parser").find("div", {"class": "merged-table-container"})
        target = curr.find("div", {"id": table_name})
        if target and merged_fragment:
            target.replace_with(merged_fragment)
        elif not merged_fragment:
            print(f"Error: Could not parse merged fragment for table {table_name}.")

def merge_tabs(prev, curr):
    """
    Merges tab content (like 'tabs-all', 'tabs-summ') into a stacked view.
    """
    for tab_name in tabs_names:
        prev_tab = prev.find("div", {"id": tab_name})
        curr_tab = curr.find("div", {"id": tab_name})

        if prev_tab is None or curr_tab is None:
            if prev_tab is None and curr_tab is None:
                continue
            print(f"Warning: Tab '{tab_name}' missing in one version. Skipping merge.")
            continue
            
        print(f"Merging tab: {tab_name}")
        
        prev_copy = copy.deepcopy(prev_tab)
        curr_copy = copy.deepcopy(curr_tab)
        
        prev_content_string = "".join(str(child) for child in prev_copy.contents)
        curr_content_string = "".join(str(child) for child in curr_copy.contents)

        stacked_html_content = f"""
        <div id="{tab_name}" class="tab-pane active merged-tab-content" style="padding: 15px; border: 1px solid #DEE2E6; border-radius: 4px; background-color: #FFFFFF;">
            <div class="container-fluid p-0">
                <h4 style="color: #333; border-bottom: 1px solid #DEE2E6; padding-bottom: 5px; margin-bottom: 15px; font-weight: 600;">Version: {prev_guide_version}</h4>
                <div class="version-prev-content" style="margin-bottom: 30px; padding: 15px; border: 1px dashed #ccc; border-radius: 4px; background-color: #F8F9FA;">
                    {prev_content_string}
                </div>

                <hr style="margin: 2rem 0; border-top: 1px solid #ccc;">

                <h4 style="color: #333; border-bottom: 1px solid #DEE2E6; padding-bottom: 5px; margin-bottom: 15px; font-weight: 600;">Version: {curr_guide_version}</h4>
                <div class="version-curr-content" style="padding: 15px; border: 1px dashed #ccc; border-radius: 4px; background-color: #F8F9FA;">
                    {curr_content_string}
                </div>
            </div>
        </div>
        """

        merged_fragment = BeautifulSoup(stacked_html_content, "html.parser").find("div", {"id": tab_name})
        target = curr.find("div", {"id": tab_name})
        
        if target and merged_fragment:
            target.replace_with(merged_fragment)
        elif not merged_fragment:
            print(f"Error: Could not parse merged fragment for tab {tab_name}.")

# -----------------------------------------------------------------------------
# HELPER FUNCTIONS: Snapshot Analysis & Migration
# -----------------------------------------------------------------------------

def suppress_child_changes(changes):
    removed_or_new = {
        c["element"]
        for c in changes
        if c["type"] in ("Removed", "New")
    }
    filtered = []
    for c in changes:
        is_child = any(
            c["element"].startswith(parent + ".")
            for parent in removed_or_new
        )
        if is_child:
            continue
        filtered.append(c)
    return filtered

def detect_breaking_changes(prev_struct, curr_struct):
    changes = []
    
    # Removed Elements
    for path, r_prev in prev_struct.items():
        if path not in curr_struct:
            is_mandatory = r_prev.get("is_mandatory", False)
            severity = "CRITICAL" if is_mandatory else "INFO"
            desc = "CRITICAL: Mandatory element removed!" if is_mandatory else "Element removed."
            
            changes.append({
                "severity": severity,
                "type": "Removed",
                "element": path,
                "desc": desc
            })

    # New Elements 
    for path, r_curr in curr_struct.items():
        if path not in prev_struct:
            is_mandatory = r_curr.get("is_mandatory", False)
            severity = "BREAKING" if is_mandatory else "INFO"
            desc = "BREAKING: New mandatory element added." if is_mandatory else "New element added."
            
            changes.append({
                "severity": severity,
                "type": "New",
                "element": path,
                "desc": desc
            })

    # Changed Elements
    for path, r_prev in prev_struct.items():
        if path in curr_struct:
            r_curr = curr_struct[path]
            if r_prev.get("card") != r_curr.get("card"):
                severity = "INFO"
                prev_card = r_prev["card"]
                curr_card = r_curr["card"]
                desc = f"Cardinality changed: {prev_card} &rarr; {curr_card}"
                
                try:
                    prev_min = int(prev_card.split("..")[0])
                    curr_min = int(curr_card.split("..")[0])
                    prev_max = prev_card.split("..")[1]
                    curr_max = curr_card.split("..")[1]
                    
                    if prev_min < curr_min:
                        severity = "BREAKING"
                        desc += " (Tightened: Optional -> Mandatory)"
                    elif prev_max == "*" and curr_max != "*":
                        severity = "BREAKING"
                        desc += " (Tightened: List -> Single)"
                    elif prev_min > curr_min:
                        desc += " (Loosened: Mandatory -> Optional)"
                except (ValueError, IndexError, KeyError):
                    pass

                changes.append({
                    "severity": severity,
                    "type": "Changed",
                    "element": path,
                    "desc": desc
                })

    def get_sort_rank(item):
        sev = item["severity"]
        typ = item["type"]
        if sev == "CRITICAL": return 1
        if sev == "BREAKING": return 2
        if sev in ["INFO", "WARNING"] and typ != "New": return 3
        if typ == "New": return 4
        return 5

    changes.sort(key=lambda x: (get_sort_rank(x), x["element"]))

    if config.get("children_hidden", True):
        changes = suppress_child_changes(changes)
        
    return changes

def parse_snapshot_table(soup):
    """
    Reads the snapshot table (Hierarchy View) and returns a dictionary of element paths.
    """
    structure = {}
    path_stack = [] 
    
    snapshot_div = soup.find("div", {"id": "tbl-snap-inner"})
    if not snapshot_div:
        return structure
    
    table = snapshot_div.find("table")
    if not table:
        return structure

    for row in table.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) < 4:
            continue
        
        name_cell = cols[0]
        # Count hierarchy depth based on images
        tbl_images = name_cell.find_all('img', src=re.compile(r'tbl_.*\.png'))
        desired_path_length = len(tbl_images)

        if desired_path_length == 0:
            continue
        
        local_name = ""
        a_tag = name_cell.find('a')
        if a_tag:
            local_name = a_tag.get_text(strip=True)
        else:
            all_text = [t.strip() for t in name_cell.stripped_strings if t.strip()]
            if all_text:
                local_name = all_text[-1]
        
        if not local_name:
            continue
        
        while len(path_stack) >= desired_path_length:
            path_stack.pop()
        
        path_stack.append(local_name)
        full_path = ".".join(path_stack)
        
        card = cols[2].get_text(strip=True)
        elem_type = cols[3].get_text(strip=True)
        
        structure[full_path] = {
            "card": card,
            "type": elem_type,
            "is_mandatory": card.split("..")[0] != "0"
        }

    return structure

# -----------------------------------------------------------------------------
# HELPER FUNCTIONS: Mapping Loading & HTML Generation
# -----------------------------------------------------------------------------

def _create_breaking_changes_table_content(auto_changes):
    html_content = ""
    
    if not auto_changes:
        html_content += '<tr><td colspan="3"><i>No critical structural changes detected automatically.</i></td></tr>'
    else:
        for change in auto_changes:
            severity = change.get("severity", "WARNING")
            ctype = change.get("type", "")
            
            bg_color = "#ffc107" 
            text_color = "#212529"
            
            if severity in ["CRITICAL", "BREAKING"]: 
                bg_color = "#dc3545" 
                text_color = "#ffffff"
            elif ctype == "New" and severity != "BREAKING":
                bg_color = "#28a745"
                text_color = "#ffffff"
            
            label_style = f"background-color: {bg_color}; color: {text_color}; padding: 4px 8px; border-radius: 4px; font-size: 0.9em; font-weight: bold;"
            
            html_content += f"""
                <tr>
                    <td style="vertical-align: middle;"><span style="{label_style}">{change['type']}</span></td>
                    <td style="vertical-align: middle;"><code>{change['element']}</code></td>
                    <td style="vertical-align: middle;">{change['desc']}</td>
                </tr>
            """
    return html_content

def _create_mapping_table_content(manual_mappings, prev_guide_version, curr_guide_version):
    html_content = ""

    if not manual_mappings:
        html_content += '<tr><td colspan="4"><i>No manual mappings defined in configuration.</i></td></tr>'
    else:
        for m in manual_mappings:
            change_type = m.get('change_type', 'INFO').upper()
            bg_color, text_color = CHANGE_TYPE_STYLES.get(change_type, CHANGE_TYPE_STYLES["INFO"])
            label_style = (
                f"background-color: {bg_color}; color: {text_color}; "
                "padding: 3px 8px; border-radius: 4px; font-size: 0.9em; font-weight: bold;"
            )
            html_content += f"""
            <tr>
                <td style="font-family: monospace; color: #d9534f;">{m.get(prev_guide_version.lower()+'_path', '-')}</td>
                <td style="font-family: monospace; color: #28a745;">{m.get(curr_guide_version.lower()+'_path', '-')}</td>
                <td><span style="{label_style}">{change_type}</span></td>
                <td>{m.get('description', '')}</td>
            </tr>
            """
    return html_content

def load_manual_mappings(artifact_id=None):
    """
    Returns manual mappings.
    """
    mappings = config.get("mappings", {})
    if artifact_id is None:
        return mappings.get("global_mappings", [])
    return mappings.get(artifact_id, [])

def create_migration_html(prev_soup, curr_soup, artifact_id):
    r_prev_struct = parse_snapshot_table(prev_soup)
    r_curr_struct = parse_snapshot_table(curr_soup)
    auto_changes = detect_breaking_changes(r_prev_struct, r_curr_struct)
    manual_mappings = load_manual_mappings() # Load global for now, or pass artifact_id if specific needed

    breaking_table_body = _create_breaking_changes_table_content(auto_changes)
    mapping_table_body = _create_mapping_table_content(manual_mappings, prev_guide_version, curr_guide_version)

    html = f"""
    <div id="tabs-migration">
        <style>
            #tabs-migration {{
                padding: 20px;
                border: 1px solid #DEE2E6;
                border-radius: 4px;
                background-color: #FFFFFF;
            }}
            #tabs-migration .container-fluid {{
                padding: 0;
            }}
            #tabs-migration h3 {{
                margin-bottom: 20px;
            }}
            #tabs-migration .info-box {{
                background-color: #f8f9fa;
                border-left: 5px solid #6c757d;
                padding: 15px;
                margin-bottom: 25px;
                border-radius: 4px;
            }}
            #tabs-migration .info-box h5 {{
                margin-top: 0;
                color: #333;
            }}
            #tabs-migration .info-box ul {{
                list-style: none;
                padding-left: 0;
                margin-bottom: 0;
            }}
            #tabs-migration .info-box li {{
                margin-bottom: 8px;
            }}
            #tabs-migration .info-box span.label {{
                padding: 3px 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 0.8em;
                margin-right: 10px;
                width: 80px;
                display: inline-block;
                text-align: center;
                color: white;
            }}
            #tabs-migration .label-critical {{ background-color: #dc3545; }}
            #tabs-migration .label-new {{ background-color: #28a745; }}
            #tabs-migration .label-info {{ background-color: #ffc107; color: #212529; }}
            #tabs-migration table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 25px;
            }}
            #tabs-migration table th,
            #tabs-migration table td {{
                padding: 8px;
                border: 1px solid #dee2e6;
            }}
            #tabs-migration table th {{
                background-color: #f8f9fa;
            }}
            #tabs-migration table.table-hover tbody tr:hover {{
                background-color: #f1f1f1;
            }}
        </style>

        <div class="container-fluid">
            <h3>Migration Guide ({prev_guide_version} &rarr; {curr_guide_version})</h3>
            <div class="info-box">
                <h5>How to read this guide:</h5>
                <p>This guide highlights structural differences between the previous and current version of the profile.</p>
                <ul>
                    <li><span class="label label-critical">CRITICAL</span> <b>Action Required:</b> Code relying on these elements will likely break.</li>
                    <li><span class="label label-new">New</span> <b>Feature:</b> New optional elements available.</li>
                    <li><span class="label label-info">Info</span> <b>Information:</b> Non-breaking changes.</li>
                </ul>
            </div>

            <h4>Automated Analysis: Breaking Changes & Structure</h4>
            <p>Differences detected by automatically comparing the snapshot tables of both versions.</p>
            <table class="grid table table-bordered table-striped">
                <thead>
                    <tr>
                        <th style="width: 150px;">Type</th>
                        <th style="width: 350px;">Element</th>
                        <th>Description / Impact</th>
                    </tr>
                </thead>
                <tbody>
                    {breaking_table_body}
                </tbody>
            </table>

            <h4>Manual Mappings ({prev_guide_version} &rarr; {curr_guide_version})</h4>
            <p>Manually defined mappings for renamed paths, moved elements, or specific migration instructions.</p>
            <table class="grid table table-bordered table-hover">
                <thead>
                    <tr>
                        <th>Old Path ({prev_guide_version})</th>
                        <th>New Path ({curr_guide_version})</th>
                        <th style="width: 120px;">Change Type</th>
                        <th>Description</th>
                    </tr>
                </thead>
                <tbody>
                    {mapping_table_body}
                </tbody>
            </table>
        </div>
    </div>
    """
    return BeautifulSoup(html, 'html.parser')

def inject_migration_tab(soup, content_fragment):
    tabs_container = soup.find("div", {"id": "tabs"})
    if tabs_container:
        ul = tabs_container.find("ul")
        if ul:
            if not ul.find("a", href="#tabs-migration"):
                new_li = soup.new_tag("li")
                new_a = soup.new_tag("a", href="#tabs-migration")
                new_a.string = "Migration Guide" 
                new_li.append(new_a)
                ul.append(new_li)
        
        existing_div = tabs_container.find("div", {"id": "tabs-migration"})
        if existing_div:
            existing_div.replace_with(content_fragment)
        else:
            tabs_container.append(content_fragment)
    else:
        print("Warning: Could not find <div id='tabs'>. Migration Tab was not inserted.")

# -----------------------------------------------------------------------------
# MAIN LOGIC: Artifact Replacement & Updating
# -----------------------------------------------------------------------------

def copy_in_current_output_folder(artifact_name):
    """
    Copies previous artifacts to current output folder.
    Paths are adjusted to be relative to the BASE_DIR.
    Previous guide is assumed to be a sibling of BASE_DIR or accessible from root.
    """
    # Assuming folder_name_prev_guide is a sibling to the BASE_DIR (AIST-PICA-R5)
    # The notebook used ../{folder_name_prev_guide}, implying it was inside R5.
    # Since we are prepending R5 to current files, we assume execution is at parent level.
    # Thus, previous guide is accessible directly by its name.
    src = f"{folder_name_prev_guide}/output/StructureDefinition-{artifact_name}.html"
    dst = f"{BASE_DIR}output/StructureDefinition-{artifact_name}.html"
    shutil.copyfile(src, dst)

def get_name_and_description(html_file_name):
    path = f"{BASE_DIR}output/{html_file_name}"
    html_file_content = BeautifulSoup(open(path, "r", encoding="utf-8").read(), 'html.parser')
    name = html_file_content.find("h2", {"id": "root"}).string.split(":")[1]
    
    # Safety check for description
    div_col = html_file_content.find("div", {"class": "col-12"})
    description = ""
    if div_col:
        ps = div_col.find_all("p")
        if len(ps) > 1:
            description = ps[1].string
            
    return name, description

def update_artifacts_table(ids_previous, ids_current):
    to_add = ids_previous - ids_current
    file_name = f"{BASE_DIR}output/artifacts.html"
    
    if not os.path.exists(file_name):
        print(f"Artifacts file not found: {file_name}")
        return

    artifacts_content = BeautifulSoup(open(file_name, "r", encoding="utf-8").read(), 'html.parser')
    artifacts_table = artifacts_content.find("table")
    
    if not artifacts_table:
        print("No table found in artifacts.html")
        return

    for artifact_name in to_add:
        try:
            copy_in_current_output_folder(artifact_name)
        except FileNotFoundError:
            continue # Probably a Mapping not a Profile
        
        try:
            name, description = get_name_and_description(f"StructureDefinition-{artifact_name}.html")

            new_row = copy.copy(artifacts_table.find("tr"))
            if not new_row: continue
            
            columns = new_row.find_all("td")
            if columns:
                columns[0].a["href"] = f"StructureDefinition-{artifact_name}.html"
                columns[0].a["title"] = f"StructureDefinition/{artifact_name}"
                columns[0].a.string = name
                if len(columns) > 1 and columns[-1].p:
                    columns[-1].p.string = description
            
            rows = artifacts_table.find_all("tr")
            rows[len(rows)-1].insert_after(new_row)
        except Exception as e:
            print(f"Error updating artifact table for {artifact_name}: {e}")

    with open(file_name, "w", encoding="utf-8") as f:
        f.write(str(artifacts_content))

def replace_artifact_file(artifact_name, folder_name_prev_guide):
    # Paths adjusted for BASE_DIR prefix and assumes sibling structure for previous guide
    prev_file_original = f"{folder_name_prev_guide}/output/StructureDefinition-{artifact_name}.html"
    curr_file_original = f"{BASE_DIR}output/StructureDefinition-{artifact_name}.html"
    
    prev_file_copy = f"{BASE_DIR}output/StructureDefinition-{artifact_name}-prev-orig.html"
    curr_file_copy = f"{BASE_DIR}output/StructureDefinition-{artifact_name}-curr-orig.html"
    
    content_prev = ""
    content_curr = ""
    
    try:
        # Load or copy the previous version
        if not os.path.isfile(prev_file_copy):
            with open(prev_file_original, "r", encoding="utf-8") as f:
                content_prev = f.read()
            with open(prev_file_copy, "w", encoding="utf-8") as f:
                f.write(content_prev)
        else:
            with open(prev_file_copy, "r", encoding="utf-8") as f:
                content_prev = f.read()
            
        # Load or copy the current version
        if not os.path.isfile(curr_file_copy):
            with open(curr_file_original, "r", encoding="utf-8") as f:
                content_curr = f.read()
            with open(curr_file_copy, "w", encoding="utf-8") as f:
                f.write(content_curr)
        else:
            with open(curr_file_copy, "r", encoding="utf-8") as f:
                content_curr = f.read()
            
    except FileNotFoundError:
        print(f"Skipping {artifact_name}: Original file not found in one of the paths.")
        return
    except UnicodeDecodeError as e:
        print(f"Error decoding file for {artifact_name}: {e}. Skipping.")
        return

    prev = BeautifulSoup(content_prev, 'html.parser')
    curr = BeautifulSoup(content_curr, 'html.parser')
    
    migration_html = create_migration_html(prev, curr, artifact_name)
    inject_migration_tab(curr, migration_html)
    
    merge_tables(prev, curr)
    merge_tabs(prev, curr)

    with open(curr_file_original, "w", encoding="utf-8") as f:
        f.write(str(curr))
    print(f"Successfully merged tables and tabs for: {artifact_name}")

def annotate_version(ids_previous, ids_current):
    file_name = f"{BASE_DIR}output/artifacts.html"
    if not os.path.exists(file_name):
        return

    artifacts_content = BeautifulSoup(open(file_name, "r", encoding="utf-8").read(), 'html.parser')
    artifacts_tables = artifacts_content.find_all("table")

    if not artifacts_tables:
        return

    if len(artifacts_tables[0].find_all("td", {"id": "IG-version"})) > 0:
        return 
    
    for artifacts_table in artifacts_tables:
        rows = artifacts_table.find_all("tr")
        for row in rows:
            a_tag = row.find("a")
            if not a_tag or not a_tag.get("title"):
                continue
                
            title = a_tag["title"].split("/")[1]
            new_colum = artifacts_content.new_tag("td")
            
            if title in ids_previous and title in ids_current:
                new_colum.string = f"{prev_guide_version}/{curr_guide_version}"
            elif title in ids_previous:
                new_colum.string = prev_guide_version
            else:
                new_colum.string = curr_guide_version
            
            new_colum["id"] = "IG-version"
            if row.td:
                row.td.insert_after(new_colum)

    with open(file_name, "w", encoding="utf-8") as f:
        f.write(str(artifacts_content))

# -----------------------------------------------------------------------------
# MAIN EXECUTION
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    # Identify FSH files and IDs
    current_fsh_dir = os.path.join(BASE_DIR, fsh_path)
    prev_fsh_dir = os.path.join(folder_name_prev_guide, fsh_path)
    
    # Check if paths exist
    if not os.path.exists(current_fsh_dir):
         print(f"Error: Current FSH directory not found: {current_fsh_dir}")
    
    current_fsh_files = find_fsh(current_fsh_dir)
    previous_fsh_files = find_fsh(prev_fsh_dir)

    # get_profile_ids_from_file_list expects the *root* dir so it can join with `fsh_path`
    # current root: BASE_DIR
    ids_current = get_profile_ids_from_file_list(current_fsh_files, BASE_DIR)
    
    ids_previous = get_profile_ids_from_file_list(previous_fsh_files, folder_name_prev_guide + "/")

    common_ids = ids_current.intersection(ids_previous)
    new_ids = ids_current - ids_previous
    removed_ids = ids_previous - ids_current

    print(f"Same Profils: {len(common_ids)}")
    print(f"New Profiles {len(new_ids)}")
    print(f"Removed Profils: {len(removed_ids)}")

    update_artifacts_table(ids_previous, ids_current)

    # Merge Profiles (Modify HTML files)
    for artifact_id in common_ids:
        print(f"Processing: {artifact_id}")
        replace_artifact_file(artifact_id, folder_name_prev_guide)

    # Annotate Versions in artifacts.html
    annotate_version(ids_previous, ids_current)