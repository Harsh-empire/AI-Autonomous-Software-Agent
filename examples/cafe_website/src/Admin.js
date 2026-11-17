import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import MenuItem from '../components/MenuItem';
import ReservationForm from '../components/ReservationForm';
import ContactForm from '../components/ContactForm';
import Navbar from '../components/Navbar';
import Footer from '../components/Footer';
import '../styles/Admin.css';

const Admin = () => {
  const [menuItems, setMenuItems] = useState([]);
  const [reservations, setReservations] = useState([]);
  const [contactInquiries, setContactInquiries] = useState([]);

  useEffect(() => {
    fetch('/api/menu')
      .then(response => response.json())
      .then(data => setMenuItems(data));

    fetch('/api/reservations')
      .then(response => response.json())
      .then(data => setReservations(data));

    fetch('/api/contact')
      .then(response => response.json())
      .then(data => setContactInquiries(data));
  }, []);

  const handleAddMenuItem = (newItem) => {
    setMenuItems([...menuItems, newItem]);
    fetch('/api/menu', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(newItem)
    });
  };

  const handleDeleteMenuItem = (id) => {
    setMenuItems(menuItems.filter(item => item.id !== id));
    fetch(`/api/menu/${id}`, {
      method: 'DELETE'
    });
  };

  const handleAddReservation = (newReservation) => {
    setReservations([...reservations, newReservation]);
    fetch('/api/reservations', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(newReservation)
    });
  };

  const handleDeleteReservation = (id) => {
    setReservations(reservations.filter(reservation => reservation.id !== id));
    fetch(`/api/reservations/${id}`, {
      method: 'DELETE'
    });
  };

  const handleAddContactInquiry = (newInquiry) => {
    setContactInquiries([...contactInquiries, newInquiry]);
    fetch('/api/contact', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(newInquiry)
    });
  };

  const handleDeleteContactInquiry = (id) => {
    setContactInquiries(contactInquiries.filter(inquiry => inquiry.id !== id));
    fetch(`/api/contact/${id}`, {
      method: 'DELETE'
    });
  };

  return (
    <div className="admin-container">
      <Navbar />
      <div className="admin-content">
        <h1>Admin Panel</h1>
        <h2>Menu Items</h2>
        <div className="menu-items">
          {menuItems.map(item => (
            <MenuItem key={item.id} item={item} onDelete={handleDeleteMenuItem} />
          ))}
        </div>
        <h2>Add New Menu Item</h2>
        <ReservationForm onSubmit={handleAddMenuItem} />
        <h2>Reservations</h2>
        <div className="reservations">
          {reservations.map(reservation => (
            <ReservationForm key={reservation.id} reservation={reservation} onDelete={handleDeleteReservation} />
          ))}
        </div>
        <h2>Add New Reservation</h2>
        <ReservationForm onSubmit={handleAddReservation} />
        <h2>Contact Inquiries</h2>
        <div className="contact-inquiries">
          {contactInquiries.map(inquiry => (
            <ContactForm key={inquiry.id} inquiry={inquiry} onDelete={handleDeleteContactInquiry} />
          ))}
        </div>
        <h2>Add New Contact Inquiry</h2>
        <ContactForm onSubmit={handleAddContactInquiry} />
      </div>
      <Footer />
    </div>
  );
};

export default Admin;