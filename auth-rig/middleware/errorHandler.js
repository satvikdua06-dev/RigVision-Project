// Error handling middleware
const errorHandler = (err, req, res, next) => {
  console.error('Error caught by handler:', {
    name: err.name,
    message: err.message,
    stack: err.stack?.split('\n')[0]
  });

  // Default error
  let error = {
    success: false,
    statusCode: err.statusCode || 500,
    message: err.message || 'Server Error'
  };

  // Mongoose bad ObjectId
  if (err.name === 'CastError') {
    error.statusCode = 400;
    error.message = 'Resource not found';
  }

  // Mongoose duplicate key
  if (err.code === 11000) {
    error.statusCode = 400;
    error.message = 'Duplicate field value entered';
  }

  // Mongoose validation error
  if (err.name === 'ValidationError') {
    error.statusCode = 400;
    error.message = Object.values(err.errors)
      .map(val => val.message)
      .join(', ');
  }

  // JWT errors
  if (err.name === 'JsonWebTokenError') {
    error.statusCode = 401;
    error.message = 'Invalid token';
  }

  if (err.name === 'TokenExpiredError') {
    error.statusCode = 401;
    error.message = 'Token expired';
  }

  res.status(error.statusCode).json(error);
};

module.exports = errorHandler;
