import json
import os

EXCLUSION_KEYWORDS = [
    # General exclusions
    "merit", "मेरिट", "claim", "objection", "दावा", "आपत्ति", "dawa", "aapatti",
    "patra", "apatra", "पात्र", "अपात्र", "document verification", "dastavej", "दस्तावेज",
    "corrigendum", "amendment", "संशोधन", "cancellation", "निरस्त", "postponed",
    "admission", "entrance", "fee", "transfer", "holiday", "calendar",
    "result", "answer key", "provisional", "selection list", "waiting list", "training",
    "hostel", "warden", "clerk", "accounting", "admin", "sports meet", "festival",
    "bank", "deposit", "tender", "panel", "fdr", "f d r", "audit", "security", "cleaning",
    "बैंक", "जमा", "निविदा", "पैनल", "अल्पावधि", "एफडीआर", "ऑडिट", "सुरक्षा",
    "new school", "naya school", "opening of", "establishment of",
    "नया विद्यालय", "विद्यालय खोलना", "खोलने", 
    # Sporting / Student Awards / Non-job events
    "swimming", "तैराकी", "chess", "शतरंज", "wushu", "वुशु", "medal", "पदक",
    "kbc", "करोड़पति", "award", "पुरस्कार", "marathon", "मैराथन", "championship", "चैम्पियनशिप",
    "olympiad", "ओलंपियाड", "science program", "साइंस प्रोग्राम", "tournament"
]

def clean_file(json_file):
    if not os.path.exists(json_file):
        return
        
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    original_count = len(data.get("jobs", []))
    valid_jobs = []
    
    for job in data.get("jobs", []):
        title = job.get("title", "").lower()
        
        # Check if title strictly contains any exclusions
        if any(exc in title for exc in EXCLUSION_KEYWORDS):
            continue
            
        # A job titled exactly "Recruitment" is usually a false positive container
        if title.strip() == "recruitment":
            continue
            
        valid_jobs.append(job)
        
    data["jobs"] = valid_jobs
    
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    # Also overwrite the .js file
    js_file = json_file.replace('.json', '.js')
    var_name = "STATE_DATA" if "central" not in json_file else "CENTRAL_DATA"
    with open(js_file, 'w', encoding='utf-8') as f:
        f.write(f"window.{var_name} = ")
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(";")
        
    print(f"[{json_file}] Kept {len(valid_jobs)} / {original_count} jobs.")

if __name__ == "__main__":
    clean_file("data.json")
    clean_file("data_central.json")
    print("Cache cleaning complete! Please restart or refresh your server to see changes.")
