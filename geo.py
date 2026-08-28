from math import radians, sin, cos, sqrt, atan2

def distance_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0088
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi/2)**2 + cos(p1)*cos(p2)*sin(dlambda/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1-a))
