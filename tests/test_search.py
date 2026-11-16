from app.search import reciprocal_rank_fusion
from support import FAQ, POLICY, make_kb


def test_ingest_then_keyword_search_finds_the_right_passage(tmp_path):
    kb = make_kb(tmp_path)
    faq, created = kb.ingest_file(FAQ, FAQ.name)
    assert created and faq["chunk_count"] > 0
    policy, _ = kb.ingest_file(POLICY, POLICY.name)

    sources = kb.retriever.search("Which tools does Northwind connect to? Salesforce?")
    assert sources[0].document_id == faq["id"]
    assert "Salesforce" in sources[0].text

    stolen = kb.retriever.search("What do I do when my laptop is stolen?")
    assert stolen[0].document_id == policy["id"]
    assert stolen[0].heading == "4. Lost or stolen devices"


def test_document_filter_limits_results(tmp_path):
    kb = make_kb(tmp_path)
    faq, _ = kb.ingest_file(FAQ, FAQ.name)
    policy, _ = kb.ingest_file(POLICY, POLICY.name)
    only_policy = kb.retriever.search("data stored encrypted", [policy["id"]])
    assert only_policy and all(s.document_id == policy["id"] for s in only_policy)
    assert kb.retriever.search("data stored encrypted", []) == []
    assert {s.document_id for s in kb.retriever.search("data stored encrypted")} == {faq["id"], policy["id"]}


def test_duplicates_are_detected_and_delete_cleans_the_index(tmp_path):
    kb = make_kb(tmp_path)
    faq, created = kb.ingest_file(FAQ, FAQ.name)
    again, created_again = kb.ingest_file(FAQ, "copy-of-faq.md")
    assert created and not created_again and again["id"] == faq["id"]
    assert kb.file_path(faq).is_file()

    assert kb.store.keyword_search(["salesforce"], None, 5)
    assert kb.delete_document(faq["id"])
    assert kb.store.keyword_search(["salesforce"], None, 5) == []
    assert not kb.file_path(faq).exists()
    assert kb.store.stats()["documents"] == 0


def test_sources_carry_sentence_offsets(tmp_path):
    kb = make_kb(tmp_path)
    kb.ingest_file(FAQ, FAQ.name)
    source = kb.retriever.search("How long is the free trial?")[0]
    page = kb.store.get_page(source.document_id, source.page_no)
    assert page[source.char_start:source.char_end] == source.text
    for start, end, _ in source.sentences:
        assert page[start:end] in source.text
    public = source.public()
    assert public["ranges"] == [[source.char_start, source.char_end]]
    assert any("14 day free trial" in q for q in public["quotes"])


def test_reciprocal_rank_fusion_rewards_agreement():
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 1, 4]])
    assert [item for item, _ in fused][:2] == [1, 3]
    assert {item for item, _ in fused} == {1, 2, 3, 4}


def test_a_document_without_text_can_be_indexed_again(tmp_path):
    kb = make_kb(tmp_path)
    blank = tmp_path / "blank.txt"
    blank.write_text("   \n\n   ")
    first, created = kb.ingest_file(blank, "blank.txt")
    assert created and first["chunk_count"] == 0 and first["note"]
    second, created_again = kb.ingest_file(blank, "blank.txt")
    assert created_again and second["id"] != first["id"]
    assert len(kb.store.list_documents()) == 1


def test_long_file_names_keep_their_extension(tmp_path):
    kb = make_kb(tmp_path)
    doc, _ = kb.ingest_file(FAQ, "x" * 300 + ".md")
    assert len(doc["filename"]) == 255 and doc["filename"].endswith(".md")
    assert kb.file_path(doc).is_file()
