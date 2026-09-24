import json

from conftest import SAMPLES

from app.importers import normalize_url, parse_file, parse_text


def read(path):
    return (SAMPLES / path).read_bytes()


def test_instagram_saved_posts():
    items = parse_file("saved_posts.json", read("instagram/your_instagram_activity/saved/saved_posts.json"))
    assert [i.url for i in items] == [
        "https://www.instagram.com/p/C1TuscanChx/",
        "https://www.instagram.com/reel/C2VeganBrwn/",  # tracking param stripped
        "https://www.instagram.com/p/C3Beach/",
    ]
    assert items[0].platform == "instagram"
    assert items[0].author == "halfbakedharvest"
    assert items[0].saved_at.startswith("2024-05-01")


def test_instagram_collections_and_mojibake():
    items = parse_file("saved_collections.json",
                       read("instagram/your_instagram_activity/saved/saved_collections.json"))
    by_url = {i.url: i for i in items}
    assert by_url["https://www.instagram.com/p/C1TuscanChx/"].collection == "Weeknight Dinners"
    assert by_url["https://www.instagram.com/reel/C2VeganBrwn/"].collection == "Desserts 🍰"


def test_whole_zip_merges_posts_and_collections():
    items = parse_file("instagram-export.zip", read("instagram-export-sample.zip"))
    assert len(items) == 3
    tuscan = next(i for i in items if "C1Tuscan" in i.url)
    assert tuscan.collection == "Weeknight Dinners" and tuscan.author == "halfbakedharvest"


def test_facebook_saved_items():
    items = parse_file("facebook-export.zip", read("facebook-export-sample.zip"))
    urls = {i.url: i for i in items}
    lasagna = urls["https://example-recipes.com/best-lasagna/"]  # fbclid dropped
    assert lasagna.platform == "facebook"  # a link saved on Facebook
    assert lasagna.title == "The Best Classic Lasagna"
    assert lasagna.author is None  # "Jane Doe saved a link." is not an author
    assert "https://www.facebook.com/quickcooks/posts/pfbid0abc" in urls


def test_facebook_outbound_wrapper_and_profiles_skipped():
    assert normalize_url("https://l.facebook.com/l.php?u=https%3A%2F%2Fsite.com%2Fpie%3Futm_source%3Dfb&h=x") == "https://site.com/pie"
    items = parse_text("https://www.instagram.com/someprofile/\nhttps://www.instagram.com/p/XYZ/")
    assert [i.url for i in items] == ["https://www.instagram.com/p/XYZ/"]


def test_html_export():
    html = """<html><body><div><a href="https://www.instagram.com/p/HTML1/">https://www.instagram.com/p/HTML1/</a></div>
      <a href="https://blog.example/soup">Best Soup</a></body></html>"""
    items = parse_file("saved_posts.html", html.encode(), "instagram")
    assert {i.url for i in items} == {"https://www.instagram.com/p/HTML1/", "https://blog.example/soup"}
    assert next(i for i in items if "soup" in i.url).title == "Best Soup"


def test_newer_label_values_layout():
    data = {"saved_saved_media": [{"label_values": [
        {"label": "URL", "value": "https://www.instagram.com/p/NEW1/", "href": "https://www.instagram.com/p/NEW1/"},
        {"label": "Owner", "value": "cookaccount"},
    ], "timestamp": 1716000000}]}
    items = parse_file("saved_posts.json", json.dumps(data).encode())
    assert items[0].url == "https://www.instagram.com/p/NEW1/"
    assert items[0].platform == "instagram"


def test_csv_list():
    text = "url,title,collection\nhttps://site.com/a,Apple Pie,Desserts\n"
    items = parse_file("links.csv", text.encode())
    assert items[0].title == "Apple Pie" and items[0].collection == "Desserts"
