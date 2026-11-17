import React, { useState } from 'react';
import ReservationForm from '../components/ReservationForm';
import Navbar from '../components/Navbar';
import Footer from '../components/Footer';
import '../styles/Reservations.css';

const Reservations = () => {
  const [successMessage, setSuccessMessage] = useState('');

  const handleSuccess = (message) => {
    setSuccessMessage(message);
  };

  return (
    <div className="reservations-page">
      <Navbar />
      <div className="container">
        <h1>Book a Table</h1>
        <ReservationForm onSuccess={handleSuccess} />
        {successMessage && <p className="success-message">{successMessage}</p>}
      </div>
      <Footer />
    </div>
  );
};

export default Reservations;