# CodeAlpha URL Shortener

A URL shortener built with Flask and SQLite as part of my CodeAlpha Backend Development Internship (Task 1).

## Features
- Shortens any valid http/https URL into a 6-character code
- Redirects from the short link to the original URL
- Tracks how many times each short link is used
- Simple web interface

## Tech Stack
Python, Flask, SQLite, HTML, CSS, JavaScript

## How to Run
1. Clone the repository
2. Create a virtual environment: `python -m venv venv`
3. Activate it: `venv\Scripts\activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Start the app: `python app.py`
6. Open http://127.0.0.1:5000 in your browser

## API Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/shorten | Send {"url": "https://..."} and get a short code |
| GET | /<short_code> | Redirects to the original URL |
| GET | /api/stats/<short_code> | Shows click count and details |

## Author
Kashmala Farrukh | CodeAlpha Backend Development Intern