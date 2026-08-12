from dharma_post_ai.models import ContentValidationError, DharmaContent


def valid_payload() -> dict[str, str]:
    return {
        "title": "ពេលស្ងប់នៃចិត្ត",
        "pali_source": "គតិធម៌សម្រាប់ពិចារណា",
        "buddhavacana": "ចិត្តដែលមានសតិ អាចស្គាល់អារម្មណ៍ដោយមិនត្រូវអារម្មណ៍នាំទៅ។",
        "explanation": "ពេលចិត្តរំខាន សូមឈប់ដកដង្ហើមជ្រៅៗ ហើយសង្កេតអារម្មណ៍។ ការសង្កេតដោយមេត្តាជួយឲ្យចិត្តទន់ភ្លន់។",
        "reflection_question": "ថ្ងៃនេះ តើអ្នកអាចផ្តល់ពេលស្ងប់ដល់ចិត្តបានប៉ុន្មាននាទី?",
        "hashtags": "#ព្រះធម៌ #DharmaPostAI #សតិ",
    }


def test_content_is_valid_and_caption_contains_essential_fields() -> None:
    content = DharmaContent.from_gemini(valid_payload(), topic="សតិ")
    caption = content.facebook_caption()

    assert content.title == "ពេលស្ងប់នៃចិត្ត"
    assert "ប្រភព៖ គតិធម៌សម្រាប់ពិចារណា" in caption
    assert "#DharmaPostAI" in caption


def test_content_rejects_empty_required_field() -> None:
    payload = valid_payload()
    payload["buddhavacana"] = ""

    try:
        DharmaContent.from_gemini(payload, topic="សតិ")
    except ContentValidationError as error:
        assert "buddhavacana" in str(error)
    else:
        raise AssertionError("Expected validation error for empty buddhavacana.")
