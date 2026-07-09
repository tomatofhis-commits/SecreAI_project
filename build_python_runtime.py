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

    # 6. Obtain official Tkinter/Tcl/Tk dependencies by extracting them from official installer
    print("Obtaining official Tkinter/Tcl/Tk dependencies...")
    installer_url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    installer_path = "python-3.11.9-amd64.exe"
    temp_install_dir = os.path.abspath("temp_python_install")
    
    try:
        # Download official installer
        if not os.path.exists(installer_path):
            print(f"Downloading official Python installer from {installer_url}...")
            urllib.request.urlretrieve(installer_url, installer_path)
            print("Downloaded successfully.")
            
        # Run silent installation to a temp local folder (UAC-free)
        print(f"Installing Python temporarily to extract files at {temp_install_dir}...")
        if os.path.exists(temp_install_dir):
            shutil.rmtree(temp_install_dir)
        os.makedirs(temp_install_dir, exist_ok=True)
        
        subprocess.run([
            installer_path,
            "/quiet",
            "InstallAllUsers=0",
            f"TargetDir={temp_install_dir}",
            "AssociateFiles=0",
            "Shortcuts=0",
            "Include_doc=0",
            "Include_launcher=0",
            "InstallLauncherAllUsers=0"
        ], check=True)
        
        # Copy Tkinter files to runtime
        print("Extracting Tkinter/Tcl/Tk files from temp installation...")
        
        # Copy DLLs and PYD (from DLLs subfolder)
        shutil.copy2(os.path.join(temp_install_dir, "DLLs", "tcl86t.dll"), runtime_path)
        shutil.copy2(os.path.join(temp_install_dir, "DLLs", "tk86t.dll"), runtime_path)
        shutil.copy2(os.path.join(temp_install_dir, "DLLs", "_tkinter.pyd"), runtime_path)
        
        # Copy tcl directory
        dest_tcl_dir = os.path.join(runtime_path, "tcl")
        if os.path.exists(dest_tcl_dir):
            shutil.rmtree(dest_tcl_dir)
        shutil.copytree(os.path.join(temp_install_dir, "tcl"), dest_tcl_dir)
        
        # Copy tkinter library directory
        dest_tkinter_dir = os.path.join(runtime_path, "Lib", "tkinter")
        if os.path.exists(dest_tkinter_dir):
            shutil.rmtree(dest_tkinter_dir)
        shutil.copytree(os.path.join(temp_install_dir, "Lib", "tkinter"), dest_tkinter_dir)
        
        print("Tkinter extraction completed successfully.")
        
    except Exception as e:
        print(f"Error: Failed to obtain Tkinter dependencies from installer: {e}")
        sys.exit(1)
        
    finally:
        # Clean up files only, DO NOT run installer /uninstall to prevent wiping system Python
        print("Cleaning up temporary installation files...")
        if os.path.exists(installer_path):
            try:
                os.remove(installer_path)
                print("Temporary installer file removed.")
            except Exception as e:
                print(f"Warning during installer file removal: {e}")
        if os.path.exists(temp_install_dir):
            try:
                shutil.rmtree(temp_install_dir)
                print("Temporary installation directory removed.")
            except Exception:
                pass

    # 6.5 Create sitecustomize.py to handle DLL path automatically
    print("Creating sitecustomize.py in site-packages...")
    sitecustomize_path = os.path.join(runtime_path, "Lib", "site-packages", "sitecustomize.py")
    sitecustomize_content = """import os
import sys
import site

# Enforce complete isolation from any system/user global site-packages
site.ENABLE_USER_SITE = False

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
