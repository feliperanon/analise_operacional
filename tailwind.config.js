/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html", "./static/**/*.js"],
  theme: {
    extend: {
      colors: {
        slate: {
            850: '#151e2e',
        }
      }
    },
  },
  plugins: [],
}
