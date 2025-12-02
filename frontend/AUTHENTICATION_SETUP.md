# Authentication & MongoDB Integration

This document describes the MongoDB and authentication integration that has been added to the ASL Avatar Generator.

## What's New

### Backend Changes

1. **MongoDB Integration** (`backend/database.py`)
   - Database connection manager
   - User and video collections
   - Indexes for efficient queries

2. **Authentication System** (`backend/auth.py`)
   - Password hashing with bcrypt
   - JWT token generation and verification
   - Secure password storage

3. **Updated API Server** (`backend/api_server.py`)
   - `/api/auth/signup` - User registration
   - `/api/auth/login` - User login
   - `/api/auth/me` - Get current user info
   - `/api/videos` - Get user's video history
   - Protected `/api/process` endpoint (requires authentication)
   - Automatic video storage in MongoDB

### Frontend Changes

1. **Login Component** (`frontend/src/Login.jsx`)
   - Email/password login form
   - Error handling
   - Token storage

2. **Signup Component** (`frontend/src/Signup.jsx`)
   - User registration form
   - Password confirmation
   - Validation

3. **Updated App Component** (`frontend/src/App.jsx`)
   - Authentication state management
   - Protected routes
   - Video history display
   - Logout functionality

4. **Enhanced Styling** (`frontend/src/App.css`)
   - Login/signup form styles
   - History section styling
   - Button styles

## Setup Instructions

### 1. Install MongoDB

See `MONGODB_SETUP.md` for detailed instructions.

### 2. Install Python Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create `backend/.env` file:

```env
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB_NAME=asl_avatar_generator
JWT_SECRET_KEY=your-secret-key-change-in-production
PORT=5031
```

### 4. Start MongoDB

```bash
# macOS
brew services start mongodb-community

# Linux
sudo systemctl start mongodb

# Or use MongoDB Atlas (cloud)
```

### 5. Start Backend Server

```bash
cd backend
python api_server.py
```

### 6. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

## API Endpoints

### Authentication

- `POST /api/auth/signup` - Register new user
  ```json
  {
    "username": "john_doe",
    "email": "john@example.com",
    "password": "securepassword"
  }
  ```

- `POST /api/auth/login` - Login user
  ```json
  {
    "email": "john@example.com",
    "password": "securepassword"
  }
  ```

- `GET /api/auth/me` - Get current user (requires auth token)

### Video Processing

- `POST /api/process` - Process video (requires auth token)
  - Headers: `Authorization: Bearer <token>`
  - Form data: `video` file

- `GET /api/videos` - Get user's video history (requires auth token)
  - Headers: `Authorization: Bearer <token>`
  - Query params: `limit` (optional, default: 50)

## Database Schema

### Users Collection
```javascript
{
  _id: ObjectId,
  username: String (unique),
  email: String (unique),
  passwordHash: String (bcrypt),
  createdAt: DateTime,
  updatedAt: DateTime
}
```

### Videos Collection
```javascript
{
  _id: ObjectId,
  userId: ObjectId (reference to users),
  jobId: String,
  transcript: String,
  videoPath: String,
  createdAt: DateTime
}
```

## Security Features

- **Password Hashing**: Bcrypt with salt
- **JWT Tokens**: Secure token-based authentication
- **CORS Protection**: Configurable origin restrictions
- **Input Validation**: Email format, password length checks
- **Unique Constraints**: Email and username uniqueness

## User Flow

1. User visits the application
2. If not logged in, sees login/signup page
3. After signup/login, receives JWT token
4. Token stored in localStorage
5. All API requests include token in Authorization header
6. Videos are automatically saved to MongoDB
7. User can view their video history
8. User can logout (clears token)

## Troubleshooting

### "Authentication required" error
- Check if token is in localStorage
- Verify token hasn't expired
- Try logging in again

### MongoDB connection error
- Ensure MongoDB is running
- Check MONGODB_URI in .env
- Verify network connectivity (if using Atlas)

### Video not saving
- Check MongoDB connection
- Verify user is authenticated
- Check backend logs for errors

## Next Steps

- Add password reset functionality
- Add email verification
- Implement video deletion
- Add user profile management
- Add video sharing features

