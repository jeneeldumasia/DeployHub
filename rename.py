import os
import sys

def is_binary(file_path):
    try:
        with open(file_path, 'tr', encoding='utf-8') as check_file:
            check_file.read(1024)
            return False
    except UnicodeDecodeError:
        return True

def rename_in_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    new_content = content.replace("ShipZen", "ShipZen")
    new_content = new_content.replace("shipzen", "shipzen")
    new_content = new_content.replace("SHIPZEN", "SHIPZEN")
    new_content = new_content.replace("Shipzen", "Shipzen")

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            f.write(new_content)
        print(f"Updated: {filepath}")

def main():
    root_dir = r"c:\Project\ShipZen"
    exclude_dirs = {'.git', 'node_modules', 'venv', '__pycache__', '.terraform', '.next'}
    
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # modify dirnames in-place to avoid traversing excluded directories
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        
        for filename in filenames:
            # skip specific files like the script itself or binaries
            if filename == 'rename.py' or filename.endswith(('.pyc', '.exe', '.dll', '.png', '.jpg', '.jpeg', '.gif', '.ico')):
                continue
                
            filepath = os.path.join(dirpath, filename)
            
            if not is_binary(filepath):
                try:
                    rename_in_file(filepath)
                except Exception as e:
                    # Ignore decoding errors for unknown binaries
                    pass

if __name__ == "__main__":
    main()
