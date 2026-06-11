const btnDelete= document.querySelectorAll('.btn-borrar');
if(btnDelete) {
  const btnArray = Array.from(btnDelete);
  btnArray.forEach((btn) => {
    btn.addEventListener('click', (e) => {
      if(!confirm('¿Está seguro de querer borrar?')){
        e.preventDefault();
      }
    });
  })
}

// Lógica selector de temas
document.addEventListener('DOMContentLoaded', () => {
  const themeStylesheet = document.getElementById('theme-stylesheet');
  const themeSelectors = document.querySelectorAll('.theme-selector');
  
  // URLs de los bootswatch para tema claro y oscuro
  const themes = {
      light: 'https://bootswatch.com/5/cosmo/bootstrap.min.css',
      dark: 'https://bootswatch.com/5/darkly/bootstrap.min.css'
  };

  // Por defecto tema claro
  const savedTheme = localStorage.getItem('selectedTheme') || 'light';
  
  if (themeStylesheet.getAttribute('href') !== themes[savedTheme]) {
      themeStylesheet.setAttribute('href', themes[savedTheme]);
  }

  // Detectar clics en las opciones del menú desplegable
  themeSelectors.forEach(selector => {
      selector.addEventListener('click', (e) => {
          e.preventDefault(); // Evitar que el link recargue la página
          const selectedTheme = selector.getAttribute('data-theme');
          
          // Cambiar el archivo CSS
          themeStylesheet.setAttribute('href', themes[selectedTheme]);
          
          // Guardar la preferencia en el navegador del usuario
          localStorage.setItem('selectedTheme', selectedTheme);
      });
  });
});