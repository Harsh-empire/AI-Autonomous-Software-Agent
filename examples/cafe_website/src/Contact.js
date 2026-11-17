import React, { useState } from 'react';
import ContactForm from '../components/ContactForm';
import Footer from '../components/Footer';
import Navbar from '../components/Navbar';
import '../styles/Contact.css';

const Contact = () => {
  const [messageSent, setMessageSent] = useState(false);

  const handleFormSubmit = (e) => {
    e.preventDefault();
    setMessageSent(true);
    setTimeout(() => {
      setMessageSent(false);
    }, 3000);
  };

  return (
    <div className="contact-page">
      <Navbar />
      <div className="contact-container">
        <h1>Contact Us</h1>
        <p>Have any questions? Feel free to reach out to us!</p>
        <ContactForm onSubmit={handleFormSubmit} />
        {messageSent && <p className="message-sent">Message sent successfully!</p>}
      </div>
      <Footer />
    </div>
  );
};

export default Contact;