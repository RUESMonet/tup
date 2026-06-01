import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.jsx";
import "antd/dist/reset.css";
import "./image.css";
import "./app.css";

createRoot(document.getElementById("root")).render(<App />);
