
import shutil
import os

source_dir = "c:/Projeto/analise_operacional/static/badges"
source_file = os.path.join(source_dir, "flash.png")

# If flash.png doesn't exist, check others
if not os.path.exists(source_file):
    files = os.listdir(source_dir)
    if files:
        source_file = os.path.join(source_dir, files[0])
    else:
        # Create a dummy file if totally empty
        source_file = os.path.join(source_dir, "badge_placeholder.png")
        with open(source_file, 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')

print(f"Using source: {source_file}")

for i in range(1, 7):
    dest = os.path.join(source_dir, f"badge_{i}.png")
    if not os.path.exists(dest):
        shutil.copy(source_file, dest)
        print(f"Created {dest}")
    else:
        print(f"Exists {dest}")
