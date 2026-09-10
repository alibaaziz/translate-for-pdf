import os
import sys
import shutil
import subprocess
import langdetect

def build_standalone_exe():
    app_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(app_dir, "dist")
    build_dir = os.path.join(app_dir, "build")

    # Locate langdetect profiles
    langdetect_dir = os.path.dirname(langdetect.__file__)
    profiles_src = os.path.join(langdetect_dir, "profiles")
    profiles_arg = f"{profiles_src};langdetect/profiles"

    print("=== ÉTAPE 1 : Compilation PyInstaller ===")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",  # Aucune console noire
        "--name", "TraducteurPDF",
        "--add-data", profiles_arg,
        "--collect-all", "ctranslate2",
        "--collect-all", "transformers",
        "--collect-all", "tokenizers",
        "--hidden-import", "bidi",
        "--hidden-import", "bidi.algorithm",
        "--collect-all", "arabic_reshaper",
        "--hidden-import", "arabic_reshaper",
        "--exclude-module", "torch",
        "--exclude-module", "torchvision",
        "--exclude-module", "torchaudio",
        "--exclude-module", "cv2",
        "--exclude-module", "scipy",
        "--exclude-module", "pyarrow",
        "--exclude-module", "onnxruntime",
        "--exclude-module", "matplotlib",
        "--exclude-module", "pandas",
        "--exclude-module", "tkinter",
        os.path.join(app_dir, "main.py")
    ]

    print("Exécution :", " ".join(cmd))
    ret = subprocess.run(cmd, cwd=app_dir)
    if ret.returncode != 0:
        print("[ERREUR] PyInstaller a échoué.")
        sys.exit(ret.returncode)

    print("\n=== ÉTAPE 2 : Intégration du modèle universel Meta NLLB-200 ===")
    target_app_folder = os.path.join(dist_dir, "TraducteurPDF")
    target_models_dir = os.path.join(target_app_folder, "models", "nllb-200-int8")

    src_models_dir = os.path.join(os.path.expanduser("~"), ".pdf_translator_offline", "models", "nllb-200-int8")

    if os.path.exists(src_models_dir):
        print(f"Copie du modèle NLLB-200 ({src_models_dir}) vers ({target_models_dir})...")
        os.makedirs(os.path.dirname(target_models_dir), exist_ok=True)
        if os.path.exists(target_models_dir):
            shutil.rmtree(target_models_dir)
        shutil.copytree(src_models_dir, target_models_dir)
        print("Modèle copié avec succès !")
    else:
        print(f"[ATTENTION] Modèle source introuvable à {src_models_dir}")

    print("\n=== ÉTAPE 2.5 : Intégration de l'accélération NVIDIA CUDA (GPU) ===")
    ctranslate2_target = os.path.join(target_app_folder, "_internal", "ctranslate2")
    if os.path.exists(ctranslate2_target):
        cublas_src = os.path.join(os.path.dirname(sys.executable), "Lib", "site-packages", "nvidia", "cublas", "bin")
        for f in ["cublas64_12.dll", "cublasLt64_12.dll"]:
            src_f = os.path.join(cublas_src, f)
            if os.path.exists(src_f):
                shutil.copy2(src_f, os.path.join(ctranslate2_target, f))
                print(f"Copié {f} pour accélération matérielle GPU.")

    print("\n=== ÉTAPE 3 : Vérification finale ===")
    exe_path = os.path.join(target_app_folder, "TraducteurPDF.exe")
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        total_folder_size = sum(
            os.path.getsize(os.path.join(dp, f))
            for dp, _, filenames in os.walk(target_app_folder)
            for f in filenames
        ) / (1024 * 1024)
        print(f"\n[SUCCÈS] Exécutable généré avec succès !")
        print(f"Fichier : {exe_path}")
        print(f"Poids total de l'application autonome : {total_folder_size:.1f} Mo (avec les 200 langues)")
        print("\nCe dossier 'TraducteurPDF' peut être zippé ou copié sur n'importe quel PC Windows sans Python.")
    else:
        print("[ERREUR] L'exécutable TraducteurPDF.exe est introuvable.")

if __name__ == "__main__":
    build_standalone_exe()
