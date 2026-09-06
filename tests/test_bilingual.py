"""Reading a bilingual subtitle file as a source and a translation at once."""

from meocosub2.bilingual import split_bilingual
from meocosub2.models import SubtitleLine


def cues(*texts: str) -> list[SubtitleLine]:
    return [
        SubtitleLine(index=i, start_ms=i * 2000, end_ms=i * 2000 + 1500, text=text)
        for i, text in enumerate(texts)
    ]


def test_a_chinese_english_cue_becomes_a_line_and_its_translation() -> None:
    lines = cues("我们就跳进那缸酸\nwe jump into the vat of acid,")

    report = split_bilingual(lines, "zh", "en")

    assert report.split_cues == 1
    assert lines[0].text == "我们就跳进那缸酸"
    assert lines[0].translated == "we jump into the vat of acid,"


def test_the_translation_may_come_first() -> None:
    """Files disagree about which row leads; the script says which is which."""
    lines = cues("we jump into the vat of acid,\n我们就跳进那缸酸")

    split_bilingual(lines, "zh", "en")

    assert lines[0].text == "我们就跳进那缸酸"
    assert lines[0].translated == "we jump into the vat of acid,"


def test_a_korean_english_cue_splits_the_same_way() -> None:
    lines = cues("천천히 하세요 보스\nTake your time, boss.")

    split_bilingual(lines, "ko", "en")

    assert lines[0].text == "천천히 하세요 보스"
    assert lines[0].translated == "Take your time, boss."


def test_a_monolingual_file_is_left_exactly_as_it_was() -> None:
    lines = cues("我们就跳进那缸酸", "你不是个发明家么")

    report = split_bilingual(lines, "zh", "en")

    assert report.split_cues == 0
    assert [line.text for line in lines] == ["我们就跳进那缸酸", "你不是个发明家么"]
    assert [line.translated for line in lines] == ["", ""]


def test_a_cue_wrapped_across_rows_is_not_two_languages() -> None:
    """A wrapped English sentence is two rows of one script, not a pair."""
    lines = cues("Take your time,\nboss.")

    report = split_bilingual(lines, "en", "zh")

    assert report.split_cues == 0
    assert lines[0].text == "Take your time,\nboss."


def test_a_file_that_is_mostly_bilingual_reports_the_ones_that_are_not() -> None:
    lines = cues(
        "我们就跳进那缸酸\nwe jump into the vat of acid,",
        "你不是个发明家么\nAren't you an inventor?",
        "慢慢来 老大",
    )

    report = split_bilingual(lines, "zh", "en")

    assert report.total_cues == 3
    assert report.split_cues == 2
    assert lines[2].translated == ""


def test_a_source_and_target_in_the_same_script_is_not_a_split() -> None:
    """Nothing to tell apart when both languages are written the same way."""
    lines = cues("Take your time, boss.\nTake your time, guv.")

    report = split_bilingual(lines, "en", "en")

    assert report.split_cues == 0


def test_more_than_two_rows_keeps_each_script_whole() -> None:
    lines = cues("我们就跳进那缸酸\n然后就没事了\nwe jump into the vat of acid,\nand that is that")

    split_bilingual(lines, "zh", "en")

    assert lines[0].text == "我们就跳进那缸酸\n然后就没事了"
    assert lines[0].translated == "we jump into the vat of acid,\nand that is that"


def test_a_handful_of_stray_latin_rows_is_not_a_bilingual_file() -> None:
    """Credits and signs appear in an otherwise monolingual file."""
    lines = cues(*["我们就跳进那缸酸"] * 9, "片尾曲\nEnd credits")

    report = split_bilingual(lines, "zh", "en")

    assert report.split_cues == 1
    assert not report.is_bilingual
