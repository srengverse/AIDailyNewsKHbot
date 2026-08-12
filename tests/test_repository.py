import asyncio

import pytest
from postgrest.exceptions import APIError

from dharma_post_ai.repository import DharmaPostRepository, SupabaseSchemaError


def test_missing_schema_error_has_actionable_instruction() -> None:
    repository = object.__new__(DharmaPostRepository)

    def broken_query() -> None:
        raise APIError(
            {
                "message": "Could not find the table 'public.dharma_posts' in the schema cache",
                "code": "PGRST205",
            }
        )

    with pytest.raises(SupabaseSchemaError, match="001_create_dharma_posts.sql"):
        asyncio.run(repository._execute(broken_query))
