const getToken = async () => {
    // Clear any old token
    localStorage.clear();
    
    // Force login
    const response = await fetch("http://127.0.0.1:8010/token", {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: 'admin', password: 'admin123' })
    });
    
    if (!response.ok) {
        console.log('[!] Login failed');
        return;
    }
    
    const data = await response.json();
    const token = data.access_token;
    console.log('[+] Token received');
    
    // Now connect WebSocket
    const ws = new WebSocket(`ws://127.0.0.1:8010/ws/optimize?token=${token}`);
    
    ws.onopen = () => {
        console.log('[+] WS Opened');
    };
    
    ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        console.log('[<] Received:', data.type, data.message);
        
        if (data.type === 'ready') {
            console.log('[SUCCESS] Connected and ready!');
            document.body.innerHTML = '<div style="padding: 20px; background: #4caf50; color: white; font-size: 24px; font-weight: bold;">✓ WebSocket Connected!</div>';
        }
    };
    
    ws.onerror = (e) => {
        console.log('[!] WS Error:', e);
    };
    
    ws.onclose = (e) => {
        console.log('[!] WS Closed', e.code);
    };
};

getToken();
