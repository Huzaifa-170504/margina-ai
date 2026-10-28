from flask import Blueprint, abort, current_app, render_template

web = Blueprint("web", __name__)


@web.get("/")
def index():
    return render_template("index.html")


@web.get("/demo")
def demo():
    if not current_app.config["DEMO_ENABLED"]:
        abort(404)
    return render_template("demo.html")


@web.get("/login")
def login():
    return render_template("login.html")


@web.get("/workspace")
def workspace():
    return render_template("workspace.html")
