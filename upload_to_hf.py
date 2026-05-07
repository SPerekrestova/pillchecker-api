from huggingface_hub import HfApi
import os
import sys

def main():
    api = HfApi()

    print("Uploading to SPerva/pillchecker-experiments...")
    # Summary and results
    files_to_experiments = [
        "benchmark_report.json",
        "benchmark_interactions_report.json",
        "benchmark_ocr_report.json",
        "/Users/svetlana/.gemini/antigravity/brain/03843218-c6ef-4e70-848e-70ccb9bf435d/evaluation_comparison.md"
    ]
    
    for f in files_to_experiments:
        if os.path.exists(f):
            print(f"Uploading {f}...")
            api.upload_file(
                path_or_fileobj=f,
                path_in_repo=os.path.basename(f),
                repo_id="SPerva/pillchecker-experiments",
                repo_type="model"
            )
        else:
            print(f"File {f} not found!")

    print("Uploading to SPerva/pillchecker-staging...")
    # Code changes
    code_files = [
        "scripts/benchmark.py",
        "scripts/benchmark_interactions.py",
        "scripts/benchmark_ocr.py"
    ]
    
    for f in code_files:
        if os.path.exists(f):
            print(f"Uploading {f}...")
            api.upload_file(
                path_or_fileobj=f,
                path_in_repo=f,
                repo_id="SPerva/pillchecker-staging",
                repo_type="space"
            )
        else:
            print(f"File {f} not found!")

if __name__ == "__main__":
    main()
