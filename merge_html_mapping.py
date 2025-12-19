import os
import re
import shutil
import copy
import json
from bs4 import BeautifulSoup

# --- Constants ---
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

# Global config placeholder
config = {}

# --- Artifact & Profile Discovery ---

def find_fsh(outpath):
    """Recursively find .fsh files in the specified path."""
    if not os.path.exists(outpath):
        print(f"Error: Path not found: {outpath}")
        return []
        
    fsh = [file for file in os.listdir(outpath) if file.lower().endswith(".fsh")]
    subfolders = [f.name for f in os.scandir(outpath) if f.is_dir()]
    for folder in subfolders:
        sub_fsh = find_fsh(os.path.join(outpath, folder))
        fsh.extend([str(folder) + "/" + str(x) for x in sub_fsh])
    return fsh

def get_profile_ids(file_content):
    """Extract profile IDs using regex."""
    return re.findall(r'Id:\s*([\w\-_]*)', file_content)

def get_profile_ids_from_file_list(file_names, base_dir, fsh_path):
    """Get all profile IDs from a list of FSH files."""
    ids = set()
    for fsh_file in file_names:
        full_path = f"{base_dir}{fsh_path}/{fsh_file}"
        try:
            with open(full_path, mode="r", encoding="utf-8") as f:
                extracted = get_profile_ids(f.read())
            print(f"From {fsh_file} extracted {extracted}")
            ids.update(extracted)
        except FileNotFoundError:
            print(f"Warning: File {full_path} not found.")
    return ids

# --- Artifact Table Updates ---

def copy_in_current_output_folder(artifact_name, prev_base, curr_base):
    """Copy previous version HTML to current output folder."""
    src = f"{prev_base}output/StructureDefinition-{artifact_name}.html"
    dst = f"{curr_base}output/StructureDefinition-{artifact_name}.html"
    shutil.copyfile(src, dst)

def get_name_and_description(html_file_name, curr_base):
    """Extract name and description from HTML file."""
    path = f"{curr_base}output/{html_file_name}"
    with open(path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    
    try:
        name = soup.find("h2", {"id": "root"}).string.split(":")[1]
        # Assuming standard FHIR IG publisher layout
        description = soup.find("div", {"class": "col-12"}).find_all("p")[1].string
    except (AttributeError, IndexError):
        name = "Unknown"
        description = "No description found."
        
    return name, description

def update_artifacts_table(ids_previous, ids_current, prev_base, curr_base):
    """Add missing previous artifacts to the current artifacts.html table."""
    to_add = ids_previous - ids_current
    file_name = f"{curr_base}output/artifacts.html"
    
    if not os.path.exists(file_name):
        print(f"Error: artifacts.html not found at {file_name}")
        return

    with open(file_name, "r", encoding="utf-8") as f:
        artifacts_content = BeautifulSoup(f.read(), 'html.parser')
        
    artifacts_table = artifacts_content.find("table")
    if not artifacts_table: return
    
    for artifact_name in to_add:
        try:
            copy_in_current_output_folder(artifact_name, prev_base, curr_base)
        except FileNotFoundError:
            continue # Likely a Mapping, not a Profile
        
        name, description = get_name_and_description(f"StructureDefinition-{artifact_name}.html", curr_base)
        
        # Clone the last row to preserve styling
        last_row = artifacts_table.find_all("tr")[-1]
        new_row = copy.copy(last_row)
        columns = new_row.find_all("td")
        
        if len(columns) > 0:
            columns[0].a["href"] = f"StructureDefinition-{artifact_name}.html"
            columns[0].a["title"] = f"StructureDefinition/{artifact_name}"
            columns[0].a.string = name
            columns[-1].p.string = description
            
            last_row.insert_after(new_row)
        
    with open(file_name, "w", encoding="utf-8") as f:
        f.write(str(artifacts_content))

# --- HTML Helper Functions ---

def add_max_width(element):
    """Prevent table overflow and force normal whitespace."""
    for row in element.find_all("td"):
        style = row.get("style", "")
        if "max-width" not in style:
            style += "; max-width: 150px"
        if "white-space" in style and "nowrap" in style:
            style = style.replace("nowrap", "normal")
        row["style"] = style.strip("; ")

def rewrite_ids(block, prefix):
    """Prefix IDs and fix JS references to avoid conflicts."""
    id_map = {}

    # Update element IDs
    for tag in block.find_all(id=True):
        original = tag["id"]
        new_id = prefix + original
        id_map[original] = new_id
        tag["id"] = new_id

    # Update anchors
    for tag in block.find_all("a", attrs={"name": True}):
        original = tag["name"]
        new_name = prefix + original
        id_map[original] = new_name
        tag["name"] = new_name

    # Update JS handlers
    def update_handler(handler):
        if not handler: return handler
        # Case insensitive value check
        for pattern in [r'(this\.value)\s*(?![.]?toLowerCase)', r'(event\.target\.value)\s*(?![.]?toLowerCase)']:
            handler = re.sub(pattern, r'\1.toLowerCase()', handler)
        # Replace IDs
        for orig, new in id_map.items():
            handler = handler.replace(f"'{orig}'", f"'{new}'").replace(f'"{orig}"', f'"{new}"').replace(f" {orig} ", f" {new} ")
        return handler

    for tag in block.find_all(lambda t: any(a.startswith("on") for a in t.attrs)):
        for attr in tag.attrs:
            if attr.startswith("on"):
                tag[attr] = update_handler(tag[attr])

    # Update internal links
    for a in block.find_all("a", href=True):
        href = a["href"]
        if href.startswith("#") and len(href) > 1 and href[1:] in id_map:
            a["href"] = f"#{prefix}{href[1:]}"

# --- Merging Logic (Tables & Tabs) ---

def merge_tables(prev, curr, prev_ver, curr_ver, table_names):
    """Merge specific tables side-by-side."""
    for table_name in table_names:
        prev_table = prev.find("div", {"id": table_name})
        curr_table = curr.find("div", {"id": table_name})
        
        if not prev_table or not curr_table:
            if not prev_table and not curr_table: continue
            print(f"Warning: Table '{table_name}' missing in one version. Skipping.")
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
                <h4 style="color: #333; border-bottom: 1px solid #DEE2E6; padding-bottom: 5px; margin-bottom: 15px;">Version: {prev_ver}</h4>
                {str(prev_wrapper)}
            </div>
            <div class="col-6" style="padding: 15px; border-left: 1px solid #DEE2E6; background-color: #FFFFFF;">
                <h4 style="color: #333; border-bottom: 1px solid #DEE2E6; padding-bottom: 5px; margin-bottom: 15px;">Version: {curr_ver}</h4>
                {str(curr_wrapper)}
            </div>
        </div>
        """
        target = curr.find("div", {"id": table_name})
        merged_frag = BeautifulSoup(merged_html, "html.parser").find("div", {"class": "merged-table-container"})
        if target and merged_frag:
            target.replace_with(merged_frag)

def merge_tabs(prev, curr, prev_ver, curr_ver, tabs_names):
    """Merge tab contents into a stacked view."""
    for tab_name in tabs_names:
        prev_tab = prev.find("div", {"id": tab_name})
        curr_tab = curr.find("div", {"id": tab_name})

        if not prev_tab or not curr_tab:
            if not prev_tab and not curr_tab: continue
            print(f"Warning: Tab '{tab_name}' missing in one version. Skipping.")
            continue
            
        print(f"Merging tab: {tab_name}")
        prev_copy = copy.deepcopy(prev_tab)
        curr_copy = copy.deepcopy(curr_tab)
        
        p_str = "".join(str(c) for c in prev_copy.contents)
        c_str = "".join(str(c) for c in curr_copy.contents)

        stacked_html = f"""
        <div id="{tab_name}" class="tab-pane active merged-tab-content" style="padding: 15px; border: 1px solid #DEE2E6; border-radius: 4px; background-color: #FFFFFF;">
            <div class="container-fluid p-0">
                <h4 style="color: #333; border-bottom: 1px solid #DEE2E6; padding-bottom: 5px; margin-bottom: 15px;">Version: {prev_ver}</h4>
                <div class="version-prev-content" style="margin-bottom: 30px; padding: 15px; border: 1px dashed #ccc; border-radius: 4px; background-color: #F8F9FA;">
                    {p_str}
                </div>
                <hr style="margin: 2rem 0; border-top: 1px solid #ccc;">
                <h4 style="color: #333; border-bottom: 1px solid #DEE2E6; padding-bottom: 5px; margin-bottom: 15px;">Version: {curr_ver}</h4>
                <div class="version-curr-content" style="padding: 15px; border: 1px dashed #ccc; border-radius: 4px; background-color: #F8F9FA;">
                    {c_str}
                </div>
            </div>
        </div>
        """
        target = curr.find("div", {"id": tab_name})
        merged_frag = BeautifulSoup(stacked_html, "html.parser").find("div", {"id": tab_name})
        if target and merged_frag:
            target.replace_with(merged_frag)

# --- Analysis & Migration Tab ---

def suppress_child_changes(changes):
    """Filter out child changes if parent is already marked New/Removed."""
    parents = {c["element"] for c in changes if c["type"] in ("Removed", "New")}
    filtered = []
    for c in changes:
        if any(c["element"].startswith(p + ".") for p in parents):
            continue
        filtered.append(c)
    return filtered

def detect_breaking_changes(prev_struct, curr_struct):
    """Compare structures to find breaking changes."""
    changes = []
    
    # Removed
    for path, r_prev in prev_struct.items():
        if path not in curr_struct:
            is_mand = r_prev.get("is_mandatory", False)
            changes.append({
                "severity": "CRITICAL" if is_mand else "INFO",
                "type": "Removed",
                "element": path,
                "desc": "CRITICAL: Mandatory element removed!" if is_mand else "Element removed."
            })

    # New
    for path, r_curr in curr_struct.items():
        if path not in prev_struct:
            is_mand = r_curr.get("is_mandatory", False)
            changes.append({
                "severity": "BREAKING" if is_mand else "INFO",
                "type": "New",
                "element": path,
                "desc": "BREAKING: New mandatory element added." if is_mand else "New element added."
            })

    # Changed
    for path, r_prev in prev_struct.items():
        if path in curr_struct:
            r_curr = curr_struct[path]
            if r_prev.get("card") != r_curr.get("card"):
                severity = "INFO"
                desc = f"Cardinality changed: {r_prev['card']} &rarr; {r_curr['card']}"
                try:
                    p_min = int(r_prev["card"].split("..")[0])
                    c_min = int(r_curr["card"].split("..")[0])
                    p_max = r_prev["card"].split("..")[1]
                    c_max = r_curr["card"].split("..")[1]
                    
                    if p_min < c_min:
                        severity = "BREAKING"
                        desc += " (Tightened: Optional -> Mandatory)"
                    elif p_max == "*" and c_max != "*":
                        severity = "BREAKING"
                        desc += " (Tightened: List -> Single)"
                    elif p_min > c_min:
                        desc += " (Loosened: Mandatory -> Optional)"
                except: pass
                
                changes.append({"severity": severity, "type": "Changed", "element": path, "desc": desc})

    # Sort
    def rank(i):
        if i["severity"] == "CRITICAL": return 1
        if i["severity"] == "BREAKING": return 2
        if i["severity"] in ["INFO", "WARNING"] and i["type"] != "New": return 3
        if i["type"] == "New": return 4
        return 5
    
    changes.sort(key=lambda x: (rank(x), x["element"]))
    
    if config.get("children_hidden", True):
        changes = suppress_child_changes(changes)
    return changes

def parse_snapshot_table(soup):
    """Parse hierarchy from snapshot table images."""
    structure = {}
    stack = []
    
    div = soup.find("div", {"id": "tbl-snap-inner"})
    if not div or not div.find("table"): return structure

    for row in div.find("table").find_all("tr"):
        cols = row.find_all("td")
        if len(cols) < 4: continue
        
        name_cell = cols[0]
        imgs = name_cell.find_all('img', src=re.compile(r'tbl_.*\.png'))
        depth = len(imgs)
        if depth == 0: continue
        
        a_tag = name_cell.find('a')
        local = a_tag.get_text(strip=True) if a_tag else (list(name_cell.stripped_strings)[-1] if list(name_cell.stripped_strings) else "")
        if not local: continue
        
        while len(stack) >= depth: stack.pop()
        stack.append(local)
        full_path = ".".join(stack)
        
        card = cols[2].get_text(strip=True)
        structure[full_path] = {
            "card": card,
            "type": cols[3].get_text(strip=True),
            "is_mandatory": card.split("..")[0] != "0"
        }
    return structure

def _create_breaking_changes_tbody(changes):
    html = ""
    if not changes: return '<tr><td colspan="3"><i>No critical structural changes detected automatically.</i></td></tr>'
    
    for c in changes:
        sev, ctype = c.get("severity", "WARNING"), c.get("type", "")
        bg, text = "#ffc107", "#212529" # Default yellow
        
        if sev in ["CRITICAL", "BREAKING"]:
            bg, text = "#dc3545", "#ffffff"
        elif ctype == "New" and sev != "BREAKING":
            bg, text = "#28a745", "#ffffff"
            
        style = f"background-color: {bg}; color: {text}; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.9em;"
        html += f"""<tr>
            <td style="vertical-align: middle;"><span style="{style}">{ctype}</span></td>
            <td style="vertical-align: middle;"><code>{c['element']}</code></td>
            <td style="vertical-align: middle;">{c['desc']}</td>
        </tr>"""
    return html

def _create_mapping_tbody(mappings, prev_ver, curr_ver):
    html = ""
    if not mappings: return '<tr><td colspan="4"><i>No manual mappings defined.</i></td></tr>'
    
    for m in mappings:
        ctype = m.get('change_type', 'INFO').upper()
        bg, text = CHANGE_TYPE_STYLES.get(ctype, CHANGE_TYPE_STYLES["INFO"])
        style = f"background-color: {bg}; color: {text}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 0.9em;"
        
        html += f"""<tr>
            <td style="font-family: monospace; color: #d9534f;">{m.get(prev_ver.lower()+'_path', '-')}</td>
            <td style="font-family: monospace; color: #28a745;">{m.get(curr_ver.lower()+'_path', '-')}</td>
            <td><span style="{style}">{ctype}</span></td>
            <td>{m.get('description', '')}</td>
        </tr>"""
    return html

def load_manual_mappings(artifact_id=None):
    """Load mappings from config."""
    mappings = config.get("mappings", {})
    return mappings.get("global_mappings", []) if artifact_id is None else mappings.get(artifact_id, [])

def create_migration_html(prev_soup, curr_soup, artifact_id, prev_ver, curr_ver):
    """Generate migration guide HTML."""
    prev_struct = parse_snapshot_table(prev_soup)
    curr_struct = parse_snapshot_table(curr_soup)
    auto_changes = detect_breaking_changes(prev_struct, curr_struct)
    manual_mappings = load_manual_mappings()

    breaking_body = _create_breaking_changes_tbody(auto_changes)
    mapping_body = _create_mapping_tbody(manual_mappings, prev_ver, curr_ver)
    
    html = f"""
    <div id="tabs-migration">
        <style>
            #tabs-migration {{ padding: 20px; border: 1px solid #DEE2E6; background: #FFF; }}
            #tabs-migration .info-box {{ background: #f8f9fa; border-left: 5px solid #6c757d; padding: 15px; margin-bottom: 25px; }}
            #tabs-migration .label {{ padding: 3px 8px; border-radius: 4px; font-weight: bold; color: white; margin-right: 10px; }}
            #tabs-migration .label-critical {{ background-color: #dc3545; }}
            #tabs-migration .label-new {{ background-color: #28a745; }}
            #tabs-migration .label-info {{ background-color: #ffc107; color: #212529; }}
            #tabs-migration table {{ width: 100%; border-collapse: collapse; margin-bottom: 25px; }}
            #tabs-migration th, #tabs-migration td {{ padding: 8px; border: 1px solid #dee2e6; }}
            #tabs-migration th {{ background: #f8f9fa; }}
        </style>
        <div class="container-fluid">
            <h3>Migration Guide ({prev_ver} &rarr; {curr_ver})</h3>
            <div class="info-box">
                <h5>How to read this guide:</h5>
                <p>Highlights structural differences.</p>
                <ul>
                    <li><span class="label label-critical">CRITICAL</span> Code break likely.</li>
                    <li><span class="label label-new">New</span> New features.</li>
                    <li><span class="label label-info">Info</span> Non-breaking.</li>
                </ul>
            </div>
            <h4>Automated Analysis</h4>
            <table class="grid table table-bordered table-striped">
                <thead><tr><th style="width: 150px;">Type</th><th style="width: 350px;">Element</th><th>Impact</th></tr></thead>
                <tbody>{breaking_body}</tbody>
            </table>
            <h4>Manual Mappings</h4>
            <table class="grid table table-bordered table-hover">
                <thead><tr><th>Old Path</th><th>New Path</th><th style="width: 120px;">Change Type</th><th>Description</th></tr></thead>
                <tbody>{mapping_body}</tbody>
            </table>
        </div>
    </div>
    """
    return BeautifulSoup(html, 'html.parser')

def inject_migration_tab(soup, content):
    """Insert Migration tab into jQuery UI structure."""
    tabs = soup.find("div", {"id": "tabs"})
    if tabs:
        ul = tabs.find("ul")
        if ul and not ul.find("a", href="#tabs-migration"):
            li = soup.new_tag("li")
            a = soup.new_tag("a", href="#tabs-migration")
            a.string = "Migration Guide"
            li.append(a)
            ul.append(li)
        
        exist = tabs.find("div", {"id": "tabs-migration"})
        if exist: exist.replace_with(content)
        else: tabs.append(content)
    else:
        print("Warning: <div id='tabs'> not found.")

def replace_artifact_file(artifact_name, prev_base, curr_base, prev_ver, curr_ver, table_names, tabs_names):
    """Load files, merge content, inject migration guide, and save."""
    prev_orig = f"{prev_base}output/StructureDefinition-{artifact_name}.html"
    curr_orig = f"{curr_base}output/StructureDefinition-{artifact_name}.html"
    
    # We store backups in the current output folder
    prev_copy_path = f"{curr_base}output/StructureDefinition-{artifact_name}-prev-orig.html"
    curr_copy_path = f"{curr_base}output/StructureDefinition-{artifact_name}-curr-orig.html"

    try:
        # Load or cache previous
        if not os.path.isfile(prev_copy_path):
            with open(prev_orig, "r", encoding="utf-8") as f: content_prev = f.read()
            with open(prev_copy_path, "w", encoding="utf-8") as f: f.write(content_prev)
        else:
            with open(prev_copy_path, "r", encoding="utf-8") as f: content_prev = f.read()

        # Load or cache current
        if not os.path.isfile(curr_copy_path):
            with open(curr_orig, "r", encoding="utf-8") as f: content_curr = f.read()
            with open(curr_copy_path, "w", encoding="utf-8") as f: f.write(content_curr)
        else:
            with open(curr_copy_path, "r", encoding="utf-8") as f: content_curr = f.read()

        prev_soup = BeautifulSoup(content_prev, 'html.parser')
        curr_soup = BeautifulSoup(content_curr, 'html.parser')

        # Operations
        mig_html = create_migration_html(prev_soup, curr_soup, artifact_name, prev_ver, curr_ver)
        inject_migration_tab(curr_soup, mig_html)
        merge_tables(prev_soup, curr_soup, prev_ver, curr_ver, table_names)
        merge_tabs(prev_soup, curr_soup, prev_ver, curr_ver, tabs_names)

        with open(curr_orig, "w", encoding="utf-8") as f:
            f.write(str(curr_soup))
        print(f"Successfully processed: {artifact_name}")

    except Exception as e:
        print(f"Error processing {artifact_name}: {e}")

def annotate_version(ids_prev, ids_curr, prev_ver, curr_ver, curr_base):
    """Add version column to artifacts table."""
    file_name = f"{curr_base}output/artifacts.html"
    if not os.path.exists(file_name): return

    with open(file_name, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    
    tables = soup.find_all("table")
    # Check if already annotated (look at first table)
    if tables and tables[0].find("td", {"id": "IG-version"}):
        return

    for table in tables:
        for row in table.find_all("tr"):
            a_tag = row.find("a")
            if not a_tag: continue
            
            title = a_tag["title"].split("/")[-1]
            new_td = soup.new_tag("td", id="IG-version")
            
            if title in ids_prev and title in ids_curr:
                new_td.string = f"{prev_ver}/{curr_ver}"
            elif title in ids_prev:
                new_td.string = prev_ver
            else:
                new_td.string = curr_ver
            
            # Insert after the name column
            row.td.insert_after(new_td)

    with open(file_name, "w", encoding="utf-8") as f:
        f.write(str(soup))

# --- Main Execution ---

def main():
    global config
    
    # Load config
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        print("Error: config.json not found.")
        return

    prev_ver = config["comparison"]["previous_version"]
    curr_ver = config["comparison"]["current_version"]
    prev_folder = config["comparison"]["previous_folder"]
    curr_folder = config["comparison"]["current_folder"]
    fsh_path = config["comparison"]["fsh_path"]
    
    prev_base = f"{prev_folder}/"
    curr_base = f"{curr_folder}/"

    print(f"Config Loaded:\nPrev: {prev_ver} ({prev_base})\nCurr: {curr_ver} ({curr_base})")

    # Discover Profiles (using dynamic base paths)
    curr_fsh = find_fsh(f"{curr_base}{fsh_path}")
    prev_fsh = find_fsh(f"{prev_base}{fsh_path}")
    
    ids_curr = get_profile_ids_from_file_list(curr_fsh, curr_base, fsh_path)
    ids_prev = get_profile_ids_from_file_list(prev_fsh, prev_base, fsh_path)
    
    common_ids = ids_curr.intersection(ids_prev)
    print(f"Stats: Same: {len(common_ids)} | New: {len(ids_curr - ids_prev)} | Removed: {len(ids_prev - ids_curr)}")

    # Update Artifacts Table
    update_artifacts_table(ids_prev, ids_curr, prev_base, curr_base)

    # Process Merges for Common Profiles
    for artifact_id in common_ids:
        replace_artifact_file(artifact_id, prev_base, curr_base, prev_ver, curr_ver, config["tables"], config["tabs"])

    # Annotate Versions
    annotate_version(ids_prev, ids_curr, prev_ver, curr_ver, curr_base)

if __name__ == "__main__":
    main()