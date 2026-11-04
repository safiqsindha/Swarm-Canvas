import pytest
from experiments.durable_staging import promote


def test_promotion_preserves_bytes_and_refuses_existing_destination(tmp_path):
    source_parent = tmp_path/'tmp'; source_parent.mkdir()
    dest = tmp_path/'durable'; dest.mkdir()
    source = source_parent/'attempt'; source.mkdir()
    (source/'events.jsonl').write_text('evidence\n')
    out = promote(source, dest)
    assert (out/'events.jsonl').read_text() == 'evidence\n'
    assert (source/'events.jsonl').exists()
    with pytest.raises(FileExistsError):
        promote(source, dest)


def test_promotion_rejects_symlink(tmp_path):
    source = tmp_path/'source'; source.mkdir()
    dest = tmp_path/'dest'; dest.mkdir()
    (source/'bad').symlink_to(dest)
    with pytest.raises(ValueError, match='Symlinks'):
        promote(source, dest)
