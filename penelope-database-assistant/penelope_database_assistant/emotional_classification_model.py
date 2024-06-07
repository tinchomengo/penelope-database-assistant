import torch
from transformers import DistilBertTokenizer, DistilBertForSequenceClassification

tokenizer = DistilBertTokenizer.from_pretrained("distilbert-base-uncased-finetuned-sst-2-english")
model = DistilBertForSequenceClassification.from_pretrained("distilbert-base-uncased-finetuned-sst-2-english")

inputs = tokenizer("Hello, my dog is gorgeous", return_tensors="pt")

with torch.no_grad():
    logits = model(**inputs).logits
predicted_class_id = logits.argmax().item()

print("Predicted class",predicted_class_id)
print("Model:",model.config.id2label[predicted_class_id])