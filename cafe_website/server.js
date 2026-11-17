const express = require('express');
const bodyParser = require('body-parser');
const cors = require('cors');
const nodemailer = require('nodemailer');

const app = express();
const port = process.env.PORT || 5000;

app.use(cors());
app.use(bodyParser.json());

// Dummy data for menu items
const menuItems = [
    { id: 1, name: 'Coffee', description: 'A rich and aromatic coffee.', price: 5 },
    { id: 2, name: 'Tea', description: 'A soothing herbal tea.', price: 4 },
    { id: 3, name: 'Sandwich', description: 'A hearty sandwich.', price: 10 }
];

// Dummy data for reservations
const reservations = [];

// Route to get menu items
app.get('/api/menu', (req, res) => {
    res.json(menuItems);
});

// Route to get reservations
app.get('/api/reservations', (req, res) => {
    res.json(reservations);
});

// Route to add a reservation
app.post('/api/reservations', (req, res) => {
    const newReservation = req.body;
    reservations.push(newReservation);
    res.status(201).json(newReservation);
});

// Route to send email
app.post('/api/send-email', async (req, res) => {
    const { name, email, message } = req.body;

    let transporter = nodemailer.createTransport({
        service: 'gmail',
        auth: {
            user: 'your-email@gmail.com',
            pass: 'your-email-password'
        }
    });

    let mailOptions = {
        from: email,
        to: 'your-email@gmail.com',
        subject: 'New Contact Form Submission',
        text: `Name: ${name}\nEmail: ${email}\nMessage: ${message}`
    };

    try {
        await transporter.sendMail(mailOptions);
        res.status(200).send('Email sent successfully');
    } catch (error) {
        res.status(500).send('Error sending email');
    }
});

app.listen(port, () => {
    console.log(`Server is running on port ${port}`);
});