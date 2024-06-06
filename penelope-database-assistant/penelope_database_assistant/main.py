import pandas as pd
from transformers import AutoTokenizer, AutoModelForTokenClassification
from transformers import pipeline
import yake

# Load the tokenizer and model for NER
tokenizer = AutoTokenizer.from_pretrained("dbmdz/bert-large-cased-finetuned-conll03-english")
model = AutoModelForTokenClassification.from_pretrained("dbmdz/bert-large-cased-finetuned-conll03-english")

# Initialize the NER pipeline
nlp = pipeline("ner", model=model, tokenizer=tokenizer)

# Function to extract NER keywords
def extract_ner_keywords(text):
    ner_results = nlp(text)
    keywords = [result['word'] for result in ner_results]
    return keywords

# YAKE keyword extraction
def yake_keywords(text):
    kw_extractor = yake.KeywordExtractor()
    keywords = kw_extractor.extract_keywords(text)
    return [kw for kw, _ in keywords]

# Combining NER and YAKE
def combined_keywords(text):
    ner_keywords = extract_ner_keywords(text)
    yake_kw = yake_keywords(text)
    # Combine and deduplicate keywords
    combined_kw = list(set(ner_keywords + yake_kw))
    return combined_kw

# Example user input
user_input = "What was bitcoin's price in May 2014?"

# Extract combined keywords
keywords = combined_keywords(user_input)
print("Combined Extracted Keywords:", keywords)
