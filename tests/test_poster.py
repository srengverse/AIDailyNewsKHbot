from pathlib import Path

from PIL import Image

from dharma_post_ai.config import Settings
from dharma_post_ai.models import DharmaContent
from dharma_post_ai.poster import DharmaPosterRenderer


def test_poster_is_a_standard_square_jpeg(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    settings = Settings(
        gemini_api_key="test",
        gemini_model="gemini-2.5-flash",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test",
        facebook_page_id="1",
        facebook_page_access_token="test",
        facebook_graph_api_version="v26.0",
        timezone_name="Asia/Phnom_Penh",
        post_time="07:00",
        auto_publish=False,
        require_approval=True,
        poster_output_dir=tmp_path,
        font_path=project_root / "Battambang-Bold.ttf",
        max_daily_posts=1,
        port=8080,
        log_level="INFO",
    )
    content = DharmaContent(
        topic="សតិ",
        title="ពេលស្ងប់នៃចិត្ត",
        pali_source="គតិធម៌សម្រាប់ពិចារណា",
        buddhavacana="ចិត្តដែលមានសតិ អាចស្គាល់អារម្មណ៍ដោយមិនត្រូវអារម្មណ៍នាំទៅ។",
        explanation="ការសង្កេតចិត្តដោយមេត្តា គាំទ្រសេចក្តីស្ងប់។",
        reflection_question="តើអ្នកអាចត្រឡប់មកស្គាល់ដង្ហើមឥឡូវនេះបានទេ?",
        hashtags="#ព្រះធម៌ #DharmaPostAI",
    )

    poster = DharmaPosterRenderer(settings).render(content)

    assert poster.output_path.is_file()
    assert poster.output_path.suffix == ".jpg"
    with Image.open(poster.output_path) as image:
        assert image.format == "JPEG"
        assert image.size == (1200, 1200)
