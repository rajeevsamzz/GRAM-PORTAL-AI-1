from upgraded_backend import app, init_db

init_db()


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
