// This is your unique Cuelinks Publisher ID.
var cId = '249857';

// This is the standard Cuelinks script. It creates a new <script> element in your HTML page
// and loads the main Cuelinks library asynchronously from their CDN.
// This script will automatically find all outbound links on your page and convert them into monetized affiliate links.
(function(d, t) {
    var s = document.createElement('script');
    s.type = 'text/javascript';
    s.async = true;
    // This logic ensures the script is loaded over https if your site is secure.
    s.src = (document.location.protocol == 'https:' ? 'https://cdn0.cuelinks.com/js/' : 'http://cdn0.cuelinks.com/js/') + 'cuelinksv2.js';
    // It appends the script to the end of the <body> to ensure it doesn't block the initial page load.
    document.getElementsByTagName('body')[0].appendChild(s);
}());
// The Cuelinks script will now run and handle link monetization on your page.