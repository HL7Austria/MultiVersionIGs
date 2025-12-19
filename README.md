# MultiVersionIGs
Project for supporting multiple Versions of the same Standard in an IG (e.g. Migraiton Guides)

# Migration HTML Tool

This Python script automates the process of comparing previous and current FSH (FHIR Shorthand) profiles, detecting structural changes, and updating HTML artifacts accordingly.

## Features

* **FSH File Handling:** Recursively finds FSH files and extracts profile IDs.
* **Change Detection:** Detects new, removed, or changed elements between two profile versions.
* **HTML Merging:** Merges tables and tabs from previous and current HTML files for side-by-side comparison.
* **Migration Guide:** Generates a Migration Guide tab highlighting automated and manual changes.
* **Artifacts Update:** Updates the artifacts HTML table with new or removed profiles and annotates versions.

## Configuration

The script loads a `config.json` from the base directory (`BASE_DIR`) containing:

* `comparison.previous_version`
* `comparison.current_version`
* `comparison.previous_folder`
* `comparison.fsh_path`
* `tables` and `tabs` to update
* `mappings` for manual adjustments
* `children_hidden` to control suppression of child changes

## Usage

```bash
python merge_html_mapping.py
```

Make sure the folder structure matches the `BASE_DIR` and the previous guide folder as specified in the config.

### Workflow

1. Identify FSH files and extract profile IDs.
2. Update artifacts table with missing or new profiles.
3. Merge profiles and update HTML files with differences.
4. Generate and inject Migration Guide tab.
5. Annotate versions in `artifacts.html`.

## Dependencies

* `beautifulsoup4`
* Standard Python libraries: `os`, `re`, `copy`, `json`

## Notes

* Paths are hardcoded relative to `BASE_DIR`.
* HTML tables and tabs are merged with styles for side-by-side visualization.
* Manual mappings from the config are applied to handle renames or special cases.
* Exceptions and warnings are printed if files are missing or cannot be processed.
