from app.services.extractors.llm_extractor import LLMExtractor

extractor = LLMExtractor()

result = extractor.extract(
    "Need cheap apartment around 15k near metro in Avadi 3bhk with furnieshed"
)

print(result)