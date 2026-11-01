"""
================================═══════════════════════════════════════════════
                    HYPERFLUX GEN 1 - DATASET COMPILER & TRAINER
================================═══════════════════════════════════════════════
"""
import json
import re
from pathlib import Path

def clean_text(text: str) -> str:
    if not text:
        return ""
    # Collapse extra spaces and normalize symbols
    text = re.sub(r'[\r\t]', ' ', text)
    text = re.sub(r' +', ' ', text)
    return text.strip()

def extract_keywords(text: str) -> set:
    """Extract core factual keywords to help the model think and match queries."""
    words = re.findall(r'\w+', text.lower())
    # Strip common filler words so the model only focuses on high-signal content
    fillers = {"what", "is", "an", "ai", "the", "a", "who", "human", "are", "you", "tell", "me", "about"}
    return [w for w in words if w not in fillers and len(w) > 1]

def build_and_train():
    print("--- Training HyperFlux Gen 1 Brain Matrix ---")
    
    # This is your training database! You can expand this list as much as you want.
    training_data = [
        {
            "prompt": "What is an AI?",
            "response": "Artificial intelligence is a computational system that processes data to simulate learning, reasoning, and problem-solving."
        },
        {
            "prompt": "What is a human?",
            "response": "A human is a biological organism characterized by advanced consciousness, emotional depth, and creative expression."
        },
        {
            "prompt": "Why is AI popular?",
            "response": "AI is popular because it automates repetitive tasks, analyzes massive datasets instantly, and helps humans amplify their productivity."
        }
    ]

    brain_matrix = {}

    for node in training_data:
        prompt_cleaned = clean_text(node["prompt"])
        response_cleaned = clean_text(node["response"])
        
        # Train the model by associating the question's core keywords with the answer
        keywords = extract_keywords(prompt_cleaned)
        
        # If the prompt itself is a definition query, map the subject directly
        match = re.search(r'(?:what is|who is|define)\s+([\w\s]+)', prompt_cleaned.lower())
        if match:
            subject = match.group(1).strip().replace("an ", "").replace("a ", "")
            brain_matrix[subject] = response_cleaned
            
        # Also store by individual keyword hooks for loose matching
        for word in keywords:
            if word not in brain_matrix:
                brain_matrix[word] = response_cleaned

    # Save the trained brain matrix file locally
    output_path = Path(__file__).resolve().parents[1] / "data" / "hf_brain.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(brain_matrix, f, indent=4, ensure_ascii=False)
        
    print(f"[Success] HyperFlux Gen 1 training complete! Saved to '{output_path}'.")

if __name__ == "__main__":
    build_and_train()
