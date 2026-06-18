import { render, screen } from "@testing-library/react";
import App from "./App";

test("renders chatbot title", () => {
  render(<App />);
  expect(screen.getByText("Chatbot")).toBeInTheDocument();
});
