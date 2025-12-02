# MongoDB Setup Guide

This guide explains how to set up MongoDB for the ASL Avatar Generator application.

## Prerequisites

- MongoDB installed and running on your system
- Python 3.8+ installed

## Installation

### 1. Install MongoDB

#### macOS (using Homebrew)
```bash
brew tap mongodb/brew
brew install mongodb-community
brew services start mongodb-community
```

#### Linux (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install -y mongodb
sudo systemctl start mongodb
sudo systemctl enable mongodb
```

#### Windows
Download and install from [MongoDB Download Center](https://www.mongodb.com/try/download/community)

### 2. Install Python Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the `backend` directory (or copy from `.env.example`):

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and set your MongoDB connection string:

```env
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB_NAME=asl_avatar_generator
JWT_SECRET_KEY=your-secret-key-change-in-production
```

### 4. Start the Backend Server

```bash
cd backend
python api_server.py
```

## MongoDB Atlas (Cloud Option)

If you prefer to use MongoDB Atlas (cloud-hosted MongoDB):

1. Sign up at [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
2. Create a free cluster
3. Get your connection string
4. Update `MONGODB_URI` in your `.env` file:

```env
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/
```

## Database Schema

The application creates two collections:

### `users` Collection
- `_id`: ObjectId (unique identifier)
- `username`: String (unique)
- `email`: String (unique)
- `passwordHash`: String (bcrypt hashed)
- `createdAt`: DateTime
- `updatedAt`: DateTime

### `videos` Collection
- `_id`: ObjectId (unique identifier)
- `userId`: ObjectId (reference to users._id)
- `jobId`: String (unique job identifier)
- `transcript`: String
- `videoPath`: String (path to video file)
- `createdAt`: DateTime

## Features

- **User Authentication**: Sign up and login with email/password
- **Video History**: All translated videos are stored per user
- **Secure Passwords**: Passwords are hashed using bcrypt
- **JWT Tokens**: Secure authentication using JSON Web Tokens

## Troubleshooting

### MongoDB Connection Error
- Ensure MongoDB is running: `mongosh` or `mongo` should connect
- Check your `MONGODB_URI` in `.env`
- Verify network connectivity if using MongoDB Atlas

### Authentication Issues
- Clear browser localStorage if tokens are corrupted
- Check JWT_SECRET_KEY is set in `.env`
- Verify user exists in database

### Video Storage
- Videos are stored in the `work/api_outputs/` directory
- Database stores references to video files
- Ensure sufficient disk space for video files

