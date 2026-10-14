import pytest

from copilot.kb import load_catalog
from copilot.kb.importer import (
    build_records,
    main,
    parse_forms,
    parse_page,
    to_yaml,
)
from copilot.kb.schema import FunctionRecord


def page_html(name, category, syntax, returns, since=None, blurb="does something"):
    version = f" (AmiBroker {since})" if since else ""
    return (
        "<html><head><title>x</title></head><body>"
        f"<h1>AFL Function Reference - {name.upper()}</h1>"
        f"<p><b>{name}</b><br> - {blurb}</p><p><i>{category}</i>{version}</p>"
        f"<table><tr><td>SYNTAX</td><td>{syntax}</td></tr>"
        f"<tr><td>RETURNS</td><td>{returns}</td></tr>"
        "<tr><td>FUNCTION</td><td>Some text about it.</td></tr></table></body></html>"
    )


def built(name, category, syntax, returns, since=None, own_pages=()):
    page = parse_page(name.lower(), page_html(name, category, syntax, returns, since))
    return build_records(page, set(own_pages) | {name.lower()})


def one(name, category, syntax, returns, since=None):
    records, _ = built(name, category, syntax, returns, since)
    (record,) = records
    return record


def shape(record):
    return [(p["name"], p["type"], p["optional"]) for p in record["params"]]


# Reading a page


def test_page_fields():
    page = parse_page(
        "applystop",
        page_html("ApplyStop", "Trading system toolbox", "ApplyStop( type )", "Nothing", "3.70"),
    )
    assert page.name == "ApplyStop"
    assert page.category_text == "Trading system toolbox"
    assert page.since == "3.70"
    assert page.syntax == "ApplyStop( type )"
    assert page.returns == "Nothing"


def test_page_without_a_version():
    page = parse_page(
        "ma", page_html("MA", "Moving averages, summation", "ma( ARRAY, periods )", "ARRAY")
    )
    assert page.since is None
    assert page.category_text == "Moving averages, summation"


@pytest.mark.parametrize(("written", "expected"), [("50", "5.0"), ("40", "4.0"), ("6.30", "6.30")])
def test_version_written_without_a_dot_is_normalised(written, expected):
    page = parse_page("x", page_html("X", "Math functions", "X()", "NUMBER", written))
    assert page.since == expected


def test_page_with_an_empty_returns_cell():
    page = parse_page(
        "reverse", page_html("Reverse", "Miscellaneous functions", "Reverse( array )", "")
    )
    assert page.returns == ""


def test_page_that_is_not_a_reference_page():
    assert parse_page("x", "<html><body>Not found</body></html>") is None


def test_the_page_blurb_is_never_kept():
    record = one("MA", "Moving averages, summation", "ma( ARRAY, periods )", "ARRAY")
    assert "description" not in record
    assert "does something" not in to_yaml(record)


# Reading a syntax line


def test_plain_parameters():
    assert parse_forms("ma( ARRAY, periods )") == [
        ("ma", [("array", "array", False), ("periods", "any", False)], False)
    ]


def test_defaults_make_parameters_optional():
    ((_, params, _),) = parse_forms("BBandTop( ARRAY, periods = 15, width = 2 )")
    assert params == [("array", "array", False), ("periods", "any", True), ("width", "any", True)]


def test_no_parameters():
    assert parse_forms("TimeNum()") == [("TimeNum", [], False)]
    assert parse_forms("GetBaseIndex( )") == [("GetBaseIndex", [], False)]


def test_quoted_parameters_are_strings():
    ((_, params, _),) = parse_forms("ParamToggle(''name'',''values'',defaultval=0 )")
    assert params == [
        ("name", "string", False),
        ("values", "string", False),
        ("defaultval", "any", True),
    ]
    ((_, params, _),) = parse_forms('fdir( "wildcard", flags = 1 )')
    assert params[0] == ("wildcard", "string", False)


def test_quote_left_unbalanced_on_the_page():
    ((_, params, _),) = parse_forms("GetFnDataForeign( ''field'', ''symbol' )")
    assert params == [("field", "string", False), ("symbol", "string", False)]


def test_comma_inside_a_default_or_a_quoted_name():
    ((_, params, _),) = parse_forms("StrExtract( list, item, separator = ',' )")
    assert [p[0] for p in params] == ["list", "item", "separator"]
    assert params[2][2] is True
    ((_, params, _),) = parse_forms("StrSort( ''tem,list,to,be,sorted'', caseSensitive = True )")
    assert len(params) == 2


def test_awkward_names_become_identifiers():
    ((_, params, _),) = parse_forms(
        "Plot( array , name , color/barcolor , style = styleLine, minvalue = {empty} )"
    )
    assert [p[0] for p in params] == ["array", "name", "color_barcolor", "style", "minvalue"]
    ((_, params, _),) = parse_forms("MxCopy( & dstmatrix, src_matrix )")
    assert [p[0] for p in params] == ["dstmatrix", "src_matrix"]
    ((_, params, _),) = parse_forms("X( 2nd, a b, a b )")
    assert [p[0] for p in params] == ["p2nd", "a_b", "a_b_2"]


def test_default_with_an_expression():
    ((_, params, _),) = parse_forms(
        "AlertIf( EXPR , command , text , type = 0, flags = 1+2+4+8, lookback = 1 );"
    )
    assert [p[2] for p in params] == [False, False, False, True, True, True]
    ((_, params, _),) = parse_forms(
        "PlotOHLC( open, style = styleCandle | styleOwnScale , XShift = 0 )"
    )
    assert [p[0] for p in params] == ["open", "style", "xshift"]


def test_dots_mark_a_variadic_function():
    assert parse_forms("printf( formatstr , ... )") == [
        ("printf", [("formatstr", "any", False)], True)
    ]
    ((_, params, variadic),) = parse_forms("SetSortColumns( col1, col2, .... )")
    assert variadic
    assert len(params) == 2


def test_two_forms_on_one_line():
    forms = parse_forms("RSI( periods = 14 ) RSIa( array, periods = 14 )")
    assert [name for name, _, _ in forms] == ["RSI", "RSIa"]
    forms = parse_forms("atan( NUMBER ), atan( ARRAY )")
    assert [name for name, _, _ in forms] == ["atan", "atan"]


def test_line_with_no_call_form():
    assert parse_forms("GetPriceStyle") == []
    assert parse_forms("createobject(") == []


# Building records


def test_record_validates_and_uses_the_heading_name():
    record = one(
        "ApplyStop", "Trading system toolbox", "applystop( type, mode = 1 )", "Nothing", "3.70"
    )
    assert record["name"] == "ApplyStop"
    assert record["doc_url"] == "https://www.amibroker.com/guide/afl/applystop.html"
    assert record["since"] == "3.70"
    assert record["returns"] == "none"
    assert FunctionRecord.model_validate(record).max_args == 2


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("ARRAY", "array"),
        ("Array", "array"),
        ("NUMBER", "number"),
        ("NUMBER (0 or 1)", "number"),
        ("NUMBER (datetime)", "number"),
        ("STRING", "string"),
        ("NOTHING", "none"),
        ("nothing", "none"),
        ("NUMBER, ARRAY", "any"),
        ("NUMBER or STRING", "any"),
        ("Matrix", "any"),
        ("OBJECT", "any"),
        ("FILE handle", "any"),
    ],
)
def test_return_types(written, expected):
    assert one("Thing", "Miscellaneous functions", "Thing( x )", written)["returns"] == expected


def test_empty_returns_cell_is_unknown_and_noted():
    records, notes = built("Flipped", "Miscellaneous functions", "Flipped( array )", "")
    assert records[0]["returns"] == "any"
    assert any("RETURNS" in note for note in notes)


def test_maths_function_documented_as_array_is_not_trusted_to_be_one():
    # Max(2, 3) is a number although the page says ARRAY.
    assert one("Max", "Math functions", "Max( ARRAY1, ARRAY2 )", "ARRAY")["returns"] == "any"
    assert (
        one("MA", "Moving averages, summation", "ma( ARRAY, periods )", "ARRAY")["returns"]
        == "array"
    )


@pytest.mark.parametrize(
    ("category_text", "expected"),
    [
        ("Math functions", "math"),
        ("Indicators", "indicator"),
        ("Moving averages, summation", "indicator"),
        ("Exploration / Indicators", "plot"),
        ("Trading system toolbox", "backtest"),
        ("Date/Time", "time"),
        ("Lowest/Highest", "lookup"),
        ("Statistical functions", "statistics"),
        ("Basic price pattern detection", "pattern"),
        ("Composites", "composite"),
        ("Referencing other symbol data", "foreign"),
        ("Time Frame functions", "timeframe"),
        ("String manipulation", "string"),
        ("Information / Categories", "info"),
        ("File Input/Output functions", "file"),
        ("Low-level graphics", "graphics"),
        ("GUI functions", "gui"),
        ("Matrix functions", "matrix"),
        ("Text-to-Speech functions", "speech"),
        ("Miscellaneous functions", "misc"),
    ],
)
def test_categories(category_text, expected):
    assert one("Thing", category_text, "Thing( x )", "NUMBER")["category"] == expected


def test_same_function_in_two_forms_takes_the_wider_range():
    record = one(
        "NumToStr",
        "String manipulation",
        "NumToStr( NUMBER, format = 1.3 ) NumToStr( ARRAY )",
        "STRING",
    )
    model = FunctionRecord.model_validate(record)
    assert (model.min_args, model.max_args) == (1, 2)


def test_second_function_on_a_page_gets_its_own_record():
    records, notes = built(
        "Wave", "Indicators", "Wave( periods = 14 ) WaveA( array, periods = 14 )", "ARRAY"
    )
    assert [r["name"] for r in records] == ["Wave", "WaveA"]
    assert records[1]["doc_url"].endswith("/wave.html")
    assert shape(records[1]) == [("array", "array", False), ("periods", "any", True)]
    assert any("WaveA" in note for note in notes)


def test_second_function_already_checked_by_hand_is_not_noted_again():
    records, notes = built(
        "RSI", "Indicators", "RSI( periods = 14 ) RSIa( array, periods = 14 )", "ARRAY"
    )
    assert [r["name"] for r in records] == ["RSI", "RSIa"]
    assert notes == []


def test_second_function_with_a_page_of_its_own_is_left_to_that_page():
    records, _ = built(
        "mtRandom",
        "Statistical functions",
        "mtRandom( seed = Null ) mtRandomA( seed = Null )",
        "NUMBER",
        own_pages=["mtrandoma"],
    )
    assert [r["name"] for r in records] == ["mtRandom"]


def test_syntax_line_naming_another_function_is_noted():
    records, notes = built(
        "ListSort", "String manipulation", "Sort( ''list'', caseSensitive = True )", "STRING"
    )
    assert [r["name"] for r in records] == ["ListSort"]
    assert len(records[0]["params"]) == 2
    assert any("Sort" in note for note in notes)


def test_variadic_record_is_noted_for_review():
    records, notes = built(
        "SomePrint", "String manipulation", "SomePrint( formatstr , ... )", "NOTHING"
    )
    assert records[0]["variadic"] is True
    assert FunctionRecord.model_validate(records[0]).max_args is None
    assert any("variadic" in note for note in notes)


def test_no_call_form_is_noted():
    records, notes = built("GetThing", "Exploration / Indicators", "GetThing", "NUMBER")
    assert records[0]["params"] == []
    assert any("call form" in note for note in notes)


def test_directive_pages_give_no_record():
    page = parse_page(
        "_include", page_html("#include", "Miscellaneous functions", "#include", "nothing")
    )
    assert build_records(page, {"_include"}) == ([], [])


def test_override_replaces_what_the_page_says():
    # printf: the page's own line would do, but the override is what is used.
    record = one("printf", "String manipulation", "printf( a, b, c )", "NUMBER")
    assert shape(record) == [("formatstr", "string", False)]
    assert record["variadic"] is True


# Writing files


def test_yaml_round_trips_through_the_validator(tmp_path):
    record = one(
        "ParamList",
        "Exploration / Indicators",
        "ParamList( ''Name'', ''Values'', defaultval = 0 )",
        "STRING",
        "4.70",
    )
    text = to_yaml(record)
    assert text.splitlines()[0] == "name: ParamList"
    assert 'since: "4.70"' in text
    assert "variadic" not in text
    assert "description" not in text
    kb = tmp_path / "kb"
    (kb / "functions").mkdir(parents=True)
    (kb / "functions" / "paramlist.yaml").write_text(text)
    (kb / "builtins.yaml").write_text("[]\n")
    (kb / "markets.yaml").write_text("[]\n")
    (kb / "VERSION").write_text("1\n")
    function = load_catalog(kb).function("ParamList")
    assert (function.min_args, function.max_args, function.returns) == (2, 3, "string")


@pytest.fixture
def cache(tmp_path):
    pages = tmp_path / "cache"
    pages.mkdir()
    (pages / "ma.html").write_text(
        page_html("MA", "Moving averages, summation", "ma( ARRAY, periods )", "ARRAY")
    )
    (pages / "hma.html").write_text(
        page_html("HMA", "Moving averages, summation", "HMA( array, range )", "ARRAY", "5.40")
    )
    (pages / "_include.html").write_text(
        page_html("#include", "Miscellaneous functions", "#include", "nothing")
    )
    return pages


@pytest.fixture
def kb(tmp_path):
    kb = tmp_path / "kb"
    (kb / "functions").mkdir(parents=True)
    (kb / "functions" / "ma.yaml").write_text(
        "name: MA\ncategory: indicator\nreturns: array\n"
        "params:\n  - {name: array, type: array, optional: false}\n"
        "  - {name: periods, type: any, optional: false}\n"
        "description: Hand written.\ndoc_url: https://www.amibroker.com/guide/afl/ma.html\n"
    )
    (kb / "builtins.yaml").write_text("[]\n")
    (kb / "markets.yaml").write_text("[]\n")
    (kb / "VERSION").write_text("1\n")
    return kb


def test_write_adds_missing_files_and_never_touches_existing_ones(cache, kb, capsys):
    before = (kb / "functions" / "ma.yaml").read_text()
    assert main(["write", str(cache), str(kb)]) == 0
    assert (kb / "functions" / "ma.yaml").read_text() == before
    assert (kb / "functions" / "hma.yaml").exists()
    assert not (kb / "functions" / "_include.yaml").exists()
    assert "1 written" in capsys.readouterr().out
    assert sorted(load_catalog(kb).functions) == ["hma", "ma"]


def test_compare_reports_missing_functions(cache, kb, capsys):
    assert main(["compare", str(cache), str(kb)]) == 1
    assert "HMA" in capsys.readouterr().out
    main(["write", str(cache), str(kb)])
    capsys.readouterr()
    assert main(["compare", str(cache), str(kb)]) == 0
    assert "0 missing" in capsys.readouterr().out


def test_compare_reports_a_signature_that_differs(cache, kb, capsys):
    path = kb / "functions" / "ma.yaml"
    path.write_text(
        path.read_text().replace("optional: false}\ndescription", "optional: true}\ndescription")
    )
    main(["write", str(cache), str(kb)])
    capsys.readouterr()
    assert main(["compare", str(cache), str(kb)]) == 0
    out = capsys.readouterr().out
    assert "MA" in out
    assert "1 differ" in out


def test_command_needs_a_known_action(capsys):
    assert main(["explode"]) == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_hand_correction_for_a_page_with_a_broken_syntax_line():
    record = one("CreateObject", "Miscellaneous functions", "createobject(", "OBJECT")
    assert shape(record) == [("server_class", "string", False)]
    records, notes = built("GetPriceStyle", "Exploration / Indicators", "GetPriceStyle", "NUMBER")
    assert records[0]["params"] == []
    assert notes == []


def test_hand_correction_for_an_empty_returns_cell():
    records, notes = built("Reverse", "Miscellaneous functions", "Reverse( array, first = 0 )", "")
    assert records[0]["returns"] == "array"
    assert notes == []
