from flask import Blueprint, jsonify

from margina.analytics.financial import METRIC_DEFINITIONS

metrics_api = Blueprint("metrics_api", __name__)


@metrics_api.get("/metrics/definitions")
def metric_definitions():
    return jsonify({"metric_version": "1.0.0", "metrics": METRIC_DEFINITIONS})
