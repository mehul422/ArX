<!-- Har Har Mahadev -->
# Tech Stack

This is the canonical stack for ArX. Keep this file in sync with any architecture changes.

| Layer | Technology | Why this specifically? |
| --- | --- | --- |
| Design | Figma | Industry standard for UI/UX prototyping. |
| Frontend | React + TypeScript | Type safety prevents bugs; massive library support. |
| Visualization | React Three Fiber | Best-in-class for web-based 3D rendering. |
| API | FastAPI (Python) | High performance; easy integration with ML/Physics libraries. |
| Physics | JPype + NumPy | Bridges Python to OpenRocket (Java) and handles math. |
| Queuing | Redis + Celery | Decouples UI from heavy math; prevents UI freezing. |
| Database | PostgreSQL | Rock-solid reliability for user data and parts libraries. |
