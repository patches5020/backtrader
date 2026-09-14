from cdcx.indicators.volume_profile_fixed import analyze, find_hvn_lvn


def test_find_hvn_lvn_excludes_poc_from_hvn():
    histogram = {100.0: 10.0, 101.0: 50.0, 102.0: 5.0, 103.0: 40.0}
    poc_price = max(histogram, key=histogram.get)  # 101.0
    hvn, lvn = find_hvn_lvn(histogram, poc_price)

    assert poc_price == 101.0
    assert hvn == 103.0  # second-tallest bucket, not POC itself
    assert lvn == 102.0  # thinnest bucket overall


def test_find_hvn_lvn_single_bucket_falls_back_to_poc():
    histogram = {100.0: 10.0}
    hvn, lvn = find_hvn_lvn(histogram, 100.0)
    assert hvn == 100.0
    assert lvn == 100.0


def test_analyze_populates_hvn_and_lvn_on_result():
    highs = [101.0, 102.0, 103.0, 104.0, 105.0]
    lows = [99.0, 100.0, 101.0, 102.0, 103.0]
    volumes = [100.0, 500.0, 50.0, 400.0, 100.0]

    result = analyze(highs, lows, volumes, price=103.0)

    assert result.hvn != 0.0
    assert result.lvn != 0.0
    assert result.hvn != result.poc  # HVN is deliberately distinct from POC
