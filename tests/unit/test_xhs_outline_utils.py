from app.ai.services.xhs.utils import derive_page_title, parse_outline


def test_parse_outline_extracts_bracket_title():
    pages = parse_outline(
        """[封面]
【标题】石家庄周边游 | 周末反向旅游首选！
【副标题】千年古韵+红色记忆一篇搞定
<page>
[内容]
标题：正定古城怎么玩
古城墙、隆兴寺、夜景路线"""
    )

    assert pages[0].page_type == "cover"
    assert pages[0].title == "石家庄周边游 | 周末反向旅游首选！"
    assert "【标题】" not in pages[0].content
    assert pages[1].title == "正定古城怎么玩"
    assert "古城墙" in pages[1].content


def test_derive_page_title_falls_back_to_first_meaningful_line():
    assert derive_page_title("避坑清单\n- 交通\n- 门票") == "避坑清单"
    assert derive_page_title("", fallback="第 3 页") == "第 3 页"
