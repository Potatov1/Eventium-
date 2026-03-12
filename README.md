# Eventium-
platform to share , make and discover events

# Eventium — Alpha v1.0.0

Eventium is a location-based event discovery platform that allows users to create, discover, and explore nearby events using geographic filtering.

This project is currently in **alpha stage** and serves as an early prototype of a local event discovery system.

---

## Features

* User authentication
* Event creation and management
* Location-based event discovery
* Distance filtering using geospatial calculations
* Simple frontend interface for browsing and interacting with events

---

## How It Works

Eventium stores event locations using latitude and longitude coordinates.
User location is compared against event locations to calculate distance and determine which events fall within a specified radius.

Nearby events are then returned and displayed to the user.

---

## Tech Stack

**Backend**

* Python
* FastAPI
* SQLite
* Uvicorn

**Frontend**

* HTML
* JavaScript

---

## Running the Project

### 1. Clone the repository

```
git clone https://github.com/yourusername/eventium.git
cd eventium
```

### 2. Install dependencies

```
pip install -r requirements.txt
```

### 3. Create environment variables

Create a `.env` file with:

```
FOURSQUARE_API_KEY=your_key_here
JWT_SECRET=your_secret_here
TOKEN_EXPIRE_MIN=120
DB_PATH=database.db
```

### 4. Run the backend

```
uvicorn main:app --reload
```

### 5. Open in browser

```
http://127.0.0.1:8000
```

---

## Project Status

This is **Alpha v1.0.0**, meaning:

* Core functionality works
* Features may change
* Security and optimization are still in progress

---

## Future Improvements

* Improved event recommendation system
* Better frontend UI
* More efficient geospatial querying
* Image uploads for events
* Deployment support

---

## License

This project is released for learning and experimentation purposes.

---

## Author

Built by Potatov1 in collaboration with yatharth1501

(thx thr GOAT for the front end and helping in backend debug and integration)
