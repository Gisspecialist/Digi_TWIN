from app.main import classify_risk, haversine_distance_km, clamp_coordinate


def test_haversine_same_point_zero():
    assert round(haversine_distance_km(0, 0, 0, 0), 6) == 0


def test_haversine_one_degree_equator():
    assert round(haversine_distance_km(0, 0, 0, 1)) == 111


def test_risk_high_pm25():
    assert classify_risk(40, 5, 0, None, None)["level"] == "high"


def test_risk_high_quake_nearby():
    assert classify_risk(5, 5, 0, None, 100)["level"] == "high"


def test_risk_moderate_event_nearby():
    assert classify_risk(5, 5, 0, 400, None)["level"] == "moderate"


def test_risk_low():
    assert classify_risk(5, 5, 0, 900, 900)["level"] == "low"


def test_coordinate_clamp():
    assert clamp_coordinate(200, -400) == (90.0, -180.0)
