import os
import sys
import urllib.request
import zipfile
import subprocess
import shutil

RUNTIME_DIR = "python_runtime"
# Fixed python version to 3.11.9 to prevent version mix/compatibility issues
PYTHON_VERSION = "3.11.9"
STABLE_PATCH_VERSIONS = {
    (3, 11): "3.11.9",
    (3, 10): "3.10.11",
    (3, 9): "3.9.13",
    (3, 12): "3.12.8"
}
ZIP_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
ZIP_PATH = "python_embed.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
GET_PIP_PATH = "get-pip.py"

# Required packages for SecreAI game_ai.py & operations
PACKAGES = [
    "google-genai",
    "openai",
    "ollama",
    "chromadb",
    "numpy",
    "pygame",
    "pystray",
    "keyboard",
    "pygetwindow",
    "Pillow",
    "onnxruntime",
    "requests",
    "flask",
    "edge_tts",
    "sounddevice",
    "SpeechRecognition",
    "websockets",
    "customtkinter",
    "psutil",
    "pyaudio",
    "tavily-python"
]

def cleanup_runtime(runtime_path):
    print("Cleaning up python_runtime to optimize package size...")
    
    # 1. Remove pip cache if it exists
    pip_cache = os.path.join(runtime_path, "pip_cache")
    if os.path.exists(pip_cache):
        try:
            shutil.rmtree(pip_cache)
            print("Removed pip cache.")
        except Exception as e:
            print(f"Failed to remove pip cache: {e}")
        
    # 2. Strict site-packages cleanup
    site_packages = os.path.join(runtime_path, "Lib", "site-packages")
    if os.path.exists(site_packages):
        # Remove massive unused packages (only used in remote Chroma but not locally)
        unneeded = ["kubernetes", "kubernetes_asyncio"]
        for pkg in unneeded:
            p = os.path.join(site_packages, pkg)
            if os.path.exists(p):
                try:
                    shutil.rmtree(p)
                    print(f"Removed unused package: {pkg}")
                except Exception as e:
                    print(f"Failed to remove package {pkg}: {e}")
                
        # Recursively remove tests, docs, samples, and examples folders
        removed_dirs_count = 0
        for root, dirs, files in os.walk(site_packages):
            for d in list(dirs):
                if d.lower() in ["test", "tests", "docs", "testing", "samples", "examples"]:
                    target = os.path.join(root, d)
                    try:
                        shutil.rmtree(target)
                        dirs.remove(d) # Avoid walking into deleted directory
                        removed_dirs_count += 1
                    except Exception:
                        pass
        print(f"Recursively removed {removed_dirs_count} non-runtime directories (tests, docs, etc.) from site-packages.")

def main():
    # Execute within the script's directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    runtime_path = os.path.join(script_dir, RUNTIME_DIR)

    python_exe = os.path.join(runtime_path, "python.exe")

    # 1. Force clear existing runtime folder to guarantee a clean build without DLL mixing (conflicts)
    if os.path.exists(runtime_path):
        print("Clearing existing python_runtime directory to guarantee a clean, unmixed build...")
        try:
            shutil.rmtree(runtime_path)
        except Exception as e:
            print(f"Warning: Failed to clean python_runtime directory: {e}")

    if not os.path.exists(runtime_path):
        print(f"Creating directory: {runtime_path}")
        os.makedirs(runtime_path)

    # 2. Download and Extract Embeddable Python
    if not os.path.exists(python_exe):
        print(f"Downloading Python embeddable zip from {ZIP_URL}...")
        try:
            urllib.request.urlretrieve(ZIP_URL, ZIP_PATH)
        except Exception as e:
            print(f"Failed to download python embed zip for version {PYTHON_VERSION}: {e}")
            major_minor = (sys.version_info.major, sys.version_info.minor)
            stable_ver = STABLE_PATCH_VERSIONS.get(major_minor, f"{sys.version_info.major}.{sys.version_info.minor}.9")
            fallback_url = f"https://www.python.org/ftp/python/{stable_ver}/python-{stable_ver}-embed-amd64.zip"
            print(f"Retrying download with stable fallback version {stable_ver} from {fallback_url}...")
            try:
                urllib.request.urlretrieve(fallback_url, ZIP_PATH)
            except Exception as e2:
                print(f"Failed to download stable fallback python embed zip: {e2}")
                sys.exit(1)
            
        print("Extracting Python embeddable zip...")
        with zipfile.ZipFile(ZIP_PATH, 'r') as zip_ref:
            zip_ref.extractall(runtime_path)
        os.remove(ZIP_PATH)
    else:
        print("Python runtime already extracted.")

    # 3. Modify ._pth file to enable site-packages loading and include Lib directory
    pth_filename = "python311._pth"
    pth_file = os.path.join(runtime_path, pth_filename)
    if os.path.exists(pth_file):
        print(f"Modifying {pth_file} to import site and include Lib...")
        # Write exact required path configuration
        pth_lines = [
            "python311.zip",
            ".",
            "Lib",
            "import site"
        ]
        with open(pth_file, "w", encoding="utf-8") as f:
            f.write("\n".join(pth_lines) + "\n")
    else:
        print(f"Warning: {pth_file} not found. Python paths might not be initialized properly.")

    # 4. Setup pip inside embeddable Python
    pip_exe = os.path.join(runtime_path, "Scripts", "pip.exe")
    if not os.path.exists(pip_exe):
        print("Downloading get-pip.py...")
        urllib.request.urlretrieve(GET_PIP_URL, GET_PIP_PATH)
        print("Installing pip inside embeddable Python...")
        subprocess.run([python_exe, GET_PIP_PATH], check=True)
        os.remove(GET_PIP_PATH)
    else:
        print("pip is already installed.")

    # 4.3 Install setuptools and wheel first to ensure build dependencies work
    print("Installing build dependencies (setuptools, wheel)...")
    try:
        subprocess.run([pip_exe, "install", "setuptools", "wheel", "--no-cache-dir"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to install build dependencies: {e}")
        sys.exit(1)

    # 5. Install packages
    print("Installing required packages...")
    for pkg in PACKAGES:
        print(f"Installing {pkg}...")
        try:
            # Use --no-cache-dir to save disk space and prevent cached build artifacts
            subprocess.run([pip_exe, "install", pkg, "--no-warn-script-location", "--no-cache-dir"], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Failed to install {pkg}: {e}")
            sys.exit(1)

    # 6. Download and extract Tkinter/Tcl/Tk dependencies from official NuGet package (independent of host)
    print("Downloading Tkinter/Tcl/Tk dependencies from NuGet python.3.11.9...")
    nupkg_url = "https://globalcdn.nuget.org/packages/python.3.11.9.nupkg"
    nupkg_path = "python_nuget.zip"
    try:
        # Download NuGet package
        urllib.request.urlretrieve(nupkg_url, nupkg_path)
        print("NuGet package downloaded successfully.")
        
        # Extract files
        with zipfile.ZipFile(nupkg_path, 'r') as zip_ref:
            # 6.1 Copy DLLs
            dll_mapping = {
                "tools/tcl86t.dll": "tcl86t.dll",
                "tools/tk86t.dll": "tk86t.dll",
                "tools/zlib1.dll": "zlib1.dll",
                "tools/DLLs/_tkinter.pyd": "_tkinter.pyd"
            }
            for src_in_zip, dest_name in dll_mapping.items():
                try:
                    data = zip_ref.read(src_in_zip)
                    dest_file_path = os.path.join(runtime_path, dest_name)
                    with open(dest_file_path, 'wb') as df:
                        df.write(data)
                    print(f"Extracted {dest_name} from NuGet package.")
                except KeyError:
                    print(f"Warning: {src_in_zip} not found in NuGet package.")
            
            # 6.2 Extract tcl directory
            dest_tcl_dir = os.path.join(runtime_path, "tcl")
            if os.path.exists(dest_tcl_dir):
                shutil.rmtree(dest_tcl_dir)
            os.makedirs(dest_tcl_dir, exist_ok=True)
            
            # 6.3 Extract Lib/tkinter directory
            dest_tkinter_dir = os.path.join(runtime_path, "Lib", "tkinter")
            if os.path.exists(dest_tkinter_dir):
                shutil.rmtree(dest_tkinter_dir)
            os.makedirs(dest_tkinter_dir, exist_ok=True)
            
            # Walk and extract matching files
            for file_info in zip_ref.infolist():
                # tcl extraction
                if file_info.filename.startswith("tools/tcl/") and not file_info.is_dir():
                    rel_path = file_info.filename[len("tools/tcl/"):]
                    dest_path = os.path.join(dest_tcl_dir, rel_path)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with open(dest_path, 'wb') as df:
                        df.write(zip_ref.read(file_info.filename))
                # tkinter library extraction
                elif file_info.filename.startswith("tools/Lib/tkinter/") and not file_info.is_dir():
                    rel_path = file_info.filename[len("tools/Lib/tkinter/"):]
                    dest_path = os.path.join(dest_tkinter_dir, rel_path)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with open(dest_path, 'wb') as df:
                        df.write(zip_ref.read(file_info.filename))
                        
            print("Extracted tcl and tkinter library folders from NuGet package.")
            
    except Exception as e:
        print(f"Error: Failed to obtain Tkinter/Tcl/Tk dependencies from NuGet: {e}")
        sys.exit(1)
    finally:
        if os.path.exists(nupkg_path):
            try:
                os.remove(nupkg_path)
            except Exception:
                pass

    # 6.5 Create sitecustomize.py to handle DLL path automatically
    print("Creating sitecustomize.py in site-packages...")
    sitecustomize_path = os.path.join(runtime_path, "Lib", "site-packages", "sitecustomize.py")
    sitecustomize_content = """import os
import sys

# Dynamically add the python_runtime root directory to DLL search paths
# site-packages is at python_runtime/Lib/site-packages
runtime_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if os.path.exists(runtime_root):
    # Add to os.add_dll_directory for Python 3.8+
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(runtime_root)
        except Exception:
            pass
    # Fallback/standard PATH env var modification
    os.environ["PATH"] = runtime_root + os.pathsep + os.environ["PATH"]
"""
    try:
        with open(sitecustomize_path, "w", encoding="utf-8") as f:
            f.write(sitecustomize_content)
        print("sitecustomize.py created successfully.")
    except Exception as e:
        print(f"Failed to create sitecustomize.py: {e}")

    # 7. Cleanup unnecessary files and folders to slim down
    cleanup_runtime(runtime_path)
    print("Python runtime build completed successfully!")

if __name__ == "__main__":
    main()
