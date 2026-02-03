
# Test script to verify extracting JSON from mixed text
import json

def clean_and_parse(text):
    print(f"--- Input ---")
    print(text[:100] + "..." if len(text) > 100 else text)
    
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    
    if start_idx != -1 and end_idx != -1:
        clean_text = text[start_idx : end_idx + 1]
    else:
        clean_text = text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
    
    clean_text = clean_text.strip()
    
    try:
        data = json.loads(clean_text)
        print("--- Parsed JSON ---")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return True
    except Exception as e:
        print(f"--- Error ---: {e}")
        return False

# Case 1: Pure JSON
case1 = '{"status": "ok"}'
clean_and_parse(case1)

# Case 2: Markdown wrapped
case2 = '```json\n{"status": "ok"}\n```'
clean_and_parse(case2)

# Case 3: Thinking Output (User Scenario)
case3 = '**Thinking**\nI should check the status.\n\n{ "status": "ok", "comment": "Checked." }'
clean_and_parse(case3)

# Case 4: Thinking Output with multiple braces inside JSON
case4 = '**Thinking** {nested thought} ... { "data": { "nested": "value" } }'
# Note: simple find('{') finds the thought's brace. This logic assumes JSON is the *last* object or the only object?
# Wait, if thought has {}, find('{') catches the first one.
# My logic finds FIRST '{' and LAST '}'.
# If text is: "**Thought {hello}** { "status": "ok" }"
# Extraction: "{hello}** { "status": "ok" }" -> Invalid JSON.
# This logic is flawed if thoughts contain braces.
