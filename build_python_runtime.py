import os
import sys
import urllib.request
import zipfile
import subprocess
import shutil

RUNTIME_DIR = "python_runtime"
# Detect host python version dynamically to ensure binary compatibility
# Pin Python version to 3.12.8 for binary consistency with the stable release
PYTHON_VERSION = "3.12.8"
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

    # 1. Clear old runtime if Python version changed to prevent dll mismatches
    python_exe = os.path.join(runtime_path, "python.exe")
    if os.path.exists(runtime_path):
        # Check if the extracted python DLL matches host major.minor
        dll_name = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
        dll_path = os.path.join(runtime_path, dll_name)
        if not os.path.exists(dll_path) and os.path.exists(python_exe):
            print("Python version mismatch detected in existing runtime. Re-creating runtime...")
            shutil.rmtree(runtime_path)

    if not os.path.exists(runtime_path):
        print(f"Creating directory: {runtime_path}")
        os.makedirs(runtime_path)

    # 2. Download and Extract Embeddable Python
    if not os.path.exists(python_exe):
        print(f"Downloading Python embeddable zip from {ZIP_URL}...")
        try:
            urllib.request.urlretrieve(ZIP_URL, ZIP_PATH)
        except Exception as e:
            print(f"Failed to download python embed zip: {e}")
            sys.exit(1)
            
        print("Extracting Python embeddable zip...")
        with zipfile.ZipFile(ZIP_PATH, 'r') as zip_ref:
            zip_ref.extractall(runtime_path)
        os.remove(ZIP_PATH)
    else:
        print("Python runtime already extracted.")

    # 3. Modify ._pth file to enable site-packages loading and include Lib directory
    pth_filename = f"python{sys.version_info.major}{sys.version_info.minor}._pth"
    pth_file = os.path.join(runtime_path, pth_filename)
    if os.path.exists(pth_file):
        print(f"Modifying {pth_file} to import site and include Lib...")
        # Write exact required path configuration
        pth_lines = [
            f"python{sys.version_info.major}{sys.version_info.minor}.zip",
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

    # 6. Copy Tkinter/Tcl/Tk dependencies from host Python
    print("Copying Tkinter/Tcl/Tk dependencies from host Python...")
    host_python_dir = sys.base_exec_prefix
    
    # 6.1 Copy DLLs from host root or DLLs folder (including Tcl/Tk and zlib dependencies)
    for dll in ["tcl86t.dll", "tk86t.dll", "zlib1.dll"]:
        src_dll = os.path.join(host_python_dir, dll)
        if os.path.exists(src_dll):
            shutil.copy2(src_dll, runtime_path)
            print(f"Copied {dll} to runtime root.")
        else:
            # Try DLLs folder as fallback
            src_dll_fallback = os.path.join(host_python_dir, "DLLs", dll)
            if os.path.exists(src_dll_fallback):
                shutil.copy2(src_dll_fallback, runtime_path)
                print(f"Copied {dll} from DLLs to runtime root.")
            
    # 6.2 Copy _tkinter.pyd from DLLs folder
    src_pyd = os.path.join(host_python_dir, "DLLs", "_tkinter.pyd")
    if os.path.exists(src_pyd):
        shutil.copy2(src_pyd, runtime_path)
        print("Copied _tkinter.pyd to runtime root.")
    else:
        # Fallback to root
        src_pyd_fallback = os.path.join(host_python_dir, "_tkinter.pyd")
        if os.path.exists(src_pyd_fallback):
            shutil.copy2(src_pyd_fallback, runtime_path)
            print("Copied _tkinter.pyd from root to runtime root.")
        
    # 6.3 Copy tcl folder from host root to runtime root
    src_tcl_dir = os.path.join(host_python_dir, "tcl")
    dest_tcl_dir = os.path.join(runtime_path, "tcl")
    if os.path.exists(src_tcl_dir):
        if os.path.exists(dest_tcl_dir):
            shutil.rmtree(dest_tcl_dir)
        shutil.copytree(src_tcl_dir, dest_tcl_dir)
        print("Copied tcl directory to runtime.")
        
    # 6.4 Copy tkinter library folder from host Lib to runtime Lib
    src_tkinter_dir = os.path.join(host_python_dir, "Lib", "tkinter")
    dest_tkinter_dir = os.path.join(runtime_path, "Lib", "tkinter")
    if os.path.exists(src_tkinter_dir):
        if os.path.exists(dest_tkinter_dir):
            shutil.rmtree(dest_tkinter_dir)
        shutil.copytree(src_tkinter_dir, dest_tkinter_dir)
        print("Copied tkinter library directory to runtime Lib.")
    else:
        print("Warning: tkinter library directory not found in host Python.")

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
