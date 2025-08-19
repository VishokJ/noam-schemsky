#!/usr/bin/env python3

import json
import sys
from pathlib import Path
from typing import Dict, Any
from identify import identify_file

def fix_rule_file(file_path: Path) -> bool:
    """
    Fix a single JSON rules file by replacing the filename-based top-level key
    with the device name extracted from the original file.
    
    Returns True if the file was modified, False if no changes were needed.
    """
    try:
        # Read the JSON file
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not isinstance(data, dict) or len(data) != 1:
            print(f"Warning: {file_path.name} doesn't have expected structure (single top-level key)")
            return False
        
        # Get the current top-level key and data
        current_key = list(data.keys())[0]
        content = data[current_key]
        
        # Extract filename from the content
        filename = content.get("filename")
        if not filename:
            print(f"Warning: {file_path.name} doesn't have 'filename' field in content")
            return False
        
        # Try to find the original file to extract device name
        test_dir = file_path.parent.parent  # Go up from output/ to TEST/
        original_file_path = test_dir / filename
        
        if not original_file_path.exists():
            print(f"Warning: Original file {original_file_path} not found for {file_path.name}")
            return False
        
        # Get device name using identify function
        identification = identify_file(original_file_path)
        device_name = identification.get("device_name")
        
        if not device_name:
            print(f"Warning: Could not extract device name from {original_file_path}")
            return False
        
        # Check if the key already matches the device name
        if current_key == device_name:
            print(f"Info: {file_path.name} already has correct device name as key: {device_name}")
            return False
        
        # Replace the key
        new_data = {device_name: content}
        
        # Write back to file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, indent=2, ensure_ascii=False)
        
        print(f"Fixed: {file_path.name} - changed '{current_key}' to '{device_name}'")
        return True
        
    except Exception as e:
        print(f"Error processing {file_path.name}: {e}")
        return False

def main():
    """
    Process all JSON files in TEST/output directory to fix their top-level keys
    from filename-based to device name-based.
    """
    output_dir = Path("TEST/output")
    
    if not output_dir.exists():
        print(f"Error: Directory {output_dir} does not exist")
        sys.exit(1)
    
    json_files = list(output_dir.glob("*.json"))
    
    if not json_files:
        print(f"No JSON files found in {output_dir}")
        return
    
    print(f"Found {len(json_files)} JSON files to process")
    
    fixed_count = 0
    for json_file in json_files:
        if fix_rule_file(json_file):
            fixed_count += 1
    
    print(f"\nProcessing complete:")
    print(f"- Total files: {len(json_files)}")
    print(f"- Files modified: {fixed_count}")
    print(f"- Files unchanged: {len(json_files) - fixed_count}")

if __name__ == "__main__":
    main()