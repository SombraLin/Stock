import sqlite3
import os
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "stock.db")

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stocks (
        symbol TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        market TEXT,
        last_sync_time TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS kline_5m (
        symbol TEXT NOT NULL,
        datetime TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        amount REAL NOT NULL,
        PRIMARY KEY (symbol, datetime)
    )
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_kline_sym_time 
    ON kline_5m (symbol, datetime ASC)
    """)

    # 预插入默认标的
    cursor.execute("""
    INSERT OR IGNORE INTO stocks (symbol, name, market) VALUES
    ('sh600036', '招商银行', 'SH'),
    ('sh000001', '上证指数', 'SH')
    """)

    # 模拟盘交易账户表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sim_account (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        cash REAL NOT NULL,
        initial_cash REAL NOT NULL,
        updated_at TEXT
    )
    """)
    cursor.execute("""
    INSERT OR IGNORE INTO sim_account (id, cash, initial_cash, updated_at)
    VALUES (1, 100000.0, 100000.0, datetime('now', 'localtime'))
    """)

    # 模拟盘持仓表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sim_position (
        symbol TEXT PRIMARY KEY,
        shares INTEGER NOT NULL,
        avg_cost REAL NOT NULL,
        updated_at TEXT
    )
    """)

    # 模拟盘交易记录流水表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sim_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        type TEXT NOT NULL,
        shares INTEGER NOT NULL,
        price REAL NOT NULL,
        amount REAL NOT NULL,
        fee REAL NOT NULL,
        pnl REAL DEFAULT 0.0,
        created_at TEXT NOT NULL,
        note TEXT
    )
    """)

    # 信号推送去重与历史记录表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS signal_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        signal_type TEXT NOT NULL,
        signal_time TEXT NOT NULL,
        price REAL NOT NULL,
        strategy TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(symbol, signal_type, signal_time)
    )
    """)

    # 飞书推送全局配置表 (键值对)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS push_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)
    cursor.execute("""
    INSERT OR IGNORE INTO push_settings (key, value, updated_at)
    VALUES ('global_enabled', '1', datetime('now', 'localtime'))
    """)

    # 各标的推送开关与过滤规则表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stock_push_configs (
        symbol TEXT PRIMARY KEY,
        enabled INTEGER NOT NULL DEFAULT 1,
        signal_filter TEXT NOT NULL DEFAULT 'ALL',
        updated_at TEXT NOT NULL
    )
    """)
    cursor.execute("""
    INSERT OR IGNORE INTO stock_push_configs (symbol, enabled, signal_filter, updated_at) VALUES
    ('sh600036', 1, 'ALL', datetime('now', 'localtime')),
    ('sz000001', 1, 'ALL', datetime('now', 'localtime'))
    """)

    conn.commit()
    conn.close()


def get_push_settings() -> Dict[str, Any]:
    """获取飞书推送全局开关及各标的的推送设置"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. 全局开关
    cursor.execute("SELECT value FROM push_settings WHERE key = 'global_enabled'")
    row = cursor.fetchone()
    global_enabled = (row["value"] == "1") if row else True
    
    # 2. 标的列表及配置
    cursor.execute("""
    SELECT s.symbol, s.name, 
           COALESCE(c.enabled, 1) as enabled, 
           COALESCE(c.signal_filter, 'ALL') as signal_filter
    FROM stocks s
    LEFT JOIN stock_push_configs c ON s.symbol = c.symbol
    WHERE s.symbol IN ('sh600036', 'sz000001')
    ORDER BY s.symbol
    """)
    rows = cursor.fetchall()
    conn.close()
    
    symbol_emoji = {
        "sh600036": "🌻",
        "sz000001": "🛡️",
        "sh000001": "📈",
        "sh510050": "🏛️"
    }
    
    stocks = []
    for r in rows:
        stocks.append({
            "symbol": r["symbol"],
            "name": r["name"],
            "icon": symbol_emoji.get(r["symbol"], "📌"),
            "enabled": bool(r["enabled"]),
            "signal_filter": r["signal_filter"]
        })
        
    return {
        "global_enabled": global_enabled,
        "stocks": stocks
    }


def update_push_settings(global_enabled: bool, stock_configs: List[Dict[str, Any]]) -> bool:
    """更新推送设置"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # 更新全局开关
        cursor.execute("""
        INSERT INTO push_settings (key, value, updated_at)
        VALUES ('global_enabled', ?, datetime('now', 'localtime'))
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """, ("1" if global_enabled else "0",))
        
        # 更新各标的配置
        for item in stock_configs:
            sym = item.get("symbol")
            if not sym:
                continue
            en = 1 if item.get("enabled", True) else 0
            sf = item.get("signal_filter", "ALL")
            if sf not in ["ALL", "BUY_ONLY", "SELL_ONLY"]:
                sf = "ALL"
            cursor.execute("""
            INSERT INTO stock_push_configs (symbol, enabled, signal_filter, updated_at)
            VALUES (?, ?, ?, datetime('now', 'localtime'))
            ON CONFLICT(symbol) DO UPDATE SET
                enabled = excluded.enabled,
                signal_filter = excluded.signal_filter,
                updated_at = excluded.updated_at
            """, (sym, en, sf))
            
        conn.commit()
        return True
    except Exception as e:
        print(f"[Database] 更新推送配置失败: {e}")
        return False
    finally:
        conn.close()



def is_signal_notified(symbol: str, signal_type: str, signal_time: str) -> bool:
    """检查某个信号是否已向用户推送过"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 1 FROM signal_notifications 
    WHERE symbol = ? AND signal_type = ? AND signal_time = ?
    LIMIT 1
    """, (symbol, signal_type, signal_time))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def record_signal_notification(symbol: str, signal_type: str, signal_time: str, price: float, strategy: str) -> bool:
    """记录一条已推送信号，支持幂等去重"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT OR IGNORE INTO signal_notifications 
        (symbol, signal_type, signal_time, price, strategy, created_at)
        VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))
        """, (symbol, signal_type, signal_time, price, strategy))
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        return False
    finally:
        conn.close()

def get_recent_notifications(limit: int = 50) -> List[Dict[str, Any]]:
    """查询最近的推送历史"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM signal_notifications ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def upsert_klines(symbol: str, records: List[Dict[str, Any]]) -> int:
    """批量插入或更新K线数据，支持幂等写入"""
    if not records:
        return 0
    conn = get_connection()
    cursor = conn.cursor()
    
    rows = [
        (
            symbol,
            r["datetime"],
            float(r["open"]),
            float(r["high"]),
            float(r["low"]),
            float(r["close"]),
            float(r["volume"]),
            float(r["amount"])
        )
        for r in records
    ]

    cursor.executemany("""
    INSERT INTO kline_5m (symbol, datetime, open, high, low, close, volume, amount)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(symbol, datetime) DO UPDATE SET
        open = excluded.open,
        high = excluded.high,
        low = excluded.low,
        close = excluded.close,
        volume = excluded.volume,
        amount = excluded.amount
    """, rows)

    cursor.execute("""
    UPDATE stocks SET last_sync_time = datetime('now', 'localtime') WHERE symbol = ?
    """, (symbol,))

    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected

def query_klines(symbol: str, limit: Optional[int] = 2000, start_time: Optional[str] = None, end_time: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    
    where_clauses = ["symbol = ?"]
    params = [symbol]
    
    if start_time:
        where_clauses.append("datetime >= ?")
        params.append(start_time)
    if end_time:
        where_clauses.append("datetime <= ?")
        params.append(end_time)
        
    where_str = " AND ".join(where_clauses)
    
    if limit:
        query = f"""
        SELECT * FROM (
            SELECT datetime, open, high, low, close, volume, amount 
            FROM kline_5m 
            WHERE {where_str}
            ORDER BY datetime DESC 
            LIMIT ?
        ) ORDER BY datetime ASC
        """
        params.append(limit)
    else:
        query = f"""
        SELECT datetime, open, high, low, close, volume, amount 
        FROM kline_5m 
        WHERE {where_str}
        ORDER BY datetime ASC
        """

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_data_stats() -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 
        s.symbol, 
        s.name, 
        COUNT(k.datetime) as bar_count,
        MIN(k.datetime) as first_time,
        MAX(k.datetime) as latest_time,
        s.last_sync_time
    FROM stocks s
    LEFT JOIN kline_5m k ON s.symbol = k.symbol
    GROUP BY s.symbol, s.name, s.last_sync_time
    """)
    rows = cursor.fetchall()
    conn.close()
    return {r["symbol"]: dict(r) for r in rows}

def get_sim_account_summary(current_price: float = 0.0, symbol: str = "sh600036") -> Dict[str, Any]:
    """获取模拟账户总资产、持仓盈亏、可用现金与交易历史"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT cash, initial_cash FROM sim_account WHERE id = 1")
    acc = cursor.fetchone()
    if not acc:
        cash, initial_cash = 100000.0, 100000.0
    else:
        cash, initial_cash = float(acc["cash"]), float(acc["initial_cash"])

    cursor.execute("SELECT symbol, shares, avg_cost FROM sim_position WHERE symbol = ?", (symbol,))
    pos = cursor.fetchone()
    shares = int(pos["shares"]) if pos else 0
    avg_cost = float(pos["avg_cost"]) if pos else 0.0

    # 计算持仓市值与浮动盈亏
    pos_market_val = shares * current_price if current_price > 0 else (shares * avg_cost)
    unrealized_pnl = (current_price - avg_cost) * shares if (shares > 0 and current_price > 0) else 0.0
    unrealized_pnl_pct = (unrealized_pnl / (avg_cost * shares) * 100) if (shares > 0 and avg_cost > 0) else 0.0

    total_assets = cash + pos_market_val
    total_pnl = total_assets - initial_cash
    total_pnl_pct = (total_pnl / initial_cash * 100) if initial_cash > 0 else 0.0

    # 获取近 50 条交易记录
    cursor.execute("""
    SELECT id, symbol, type, shares, price, amount, fee, pnl, created_at, note 
    FROM sim_trades 
    ORDER BY id DESC LIMIT 50
    """)
    trades = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return {
        "cash": round(cash, 2),
        "initial_cash": round(initial_cash, 2),
        "total_assets": round(total_assets, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "position": {
            "symbol": symbol,
            "shares": shares,
            "avg_cost": round(avg_cost, 2),
            "market_value": round(pos_market_val, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
            "current_price": round(current_price, 2)
        },
        "trades": trades
    }

def execute_sim_trade(symbol: str, trade_type: str, shares: int, price: float, note: str = "") -> Dict[str, Any]:
    """
    执行模拟买入/卖出交易
    A股真实费率：买入佣金万2.5 (单笔最低5元)，卖出佣金万2.5 + 印花税千0.5 (卖出合计约0.075%)
    """
    trade_type = trade_type.upper()
    if shares <= 0 or price <= 0:
        return {"status": "error", "message": "数量或价格必须大于0"}
    if shares % 100 != 0 and trade_type == "BUY":
        return {"status": "error", "message": "A股买入必须是整手 (100股的整数倍)"}

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT cash, initial_cash FROM sim_account WHERE id = 1")
        acc = cursor.fetchone()
        cash = float(acc["cash"]) if acc else 100000.0

        cursor.execute("SELECT shares, avg_cost FROM sim_position WHERE symbol = ?", (symbol,))
        pos = cursor.fetchone()
        cur_shares = int(pos["shares"]) if pos else 0
        cur_avg_cost = float(pos["avg_cost"]) if pos else 0.0

        gross_amount = shares * price
        pnl = 0.0

        if trade_type == "BUY":
            # 佣金：万2.5，最低5元
            fee = max(5.0, gross_amount * 0.00025)
            total_cost = gross_amount + fee
            if cash < total_cost:
                conn.close()
                return {"status": "error", "message": f"可用现金不足！需要 ¥{total_cost:.2f}，当前可用 ¥{cash:.2f}"}

            new_cash = cash - total_cost
            new_shares = cur_shares + shares
            new_avg_cost = ((cur_shares * cur_avg_cost) + total_cost) / new_shares if new_shares > 0 else price

            # 更新账户与持仓
            cursor.execute("UPDATE sim_account SET cash = ?, updated_at = datetime('now', 'localtime') WHERE id = 1", (new_cash,))
            cursor.execute("""
            INSERT INTO sim_position (symbol, shares, avg_cost, updated_at) 
            VALUES (?, ?, ?, datetime('now', 'localtime'))
            ON CONFLICT(symbol) DO UPDATE SET 
                shares = excluded.shares, 
                avg_cost = excluded.avg_cost, 
                updated_at = excluded.updated_at
            """, (symbol, new_shares, new_avg_cost))

        elif trade_type == "SELL":
            if cur_shares < shares:
                conn.close()
                return {"status": "error", "message": f"可用持仓不足！欲卖出 {shares} 股，当前持仓 {cur_shares} 股"}

            # 卖出佣金 + 印花税(0.05%)
            commission = max(5.0, gross_amount * 0.00025)
            stamp_tax = gross_amount * 0.0005
            fee = commission + stamp_tax

            net_proceeds = gross_amount - fee
            new_cash = cash + net_proceeds
            new_shares = cur_shares - shares
            # 平仓已实现盈亏 = (卖出价 - 持仓成本价) * 卖出股数 - 交易费用
            pnl = (price - cur_avg_cost) * shares - fee

            cursor.execute("UPDATE sim_account SET cash = ?, updated_at = datetime('now', 'localtime') WHERE id = 1", (new_cash,))
            if new_shares == 0:
                cursor.execute("DELETE FROM sim_position WHERE symbol = ?", (symbol,))
            else:
                cursor.execute("UPDATE sim_position SET shares = ?, updated_at = datetime('now', 'localtime') WHERE symbol = ?", (new_shares, symbol))
        else:
            conn.close()
            return {"status": "error", "message": "不支持的交易类型"}

        # 记录流水
        cursor.execute("""
        INSERT INTO sim_trades (symbol, type, shares, price, amount, fee, pnl, created_at, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'), ?)
        """, (symbol, trade_type, shares, price, gross_amount, fee, pnl, note))

        conn.commit()
        conn.close()
        return {
            "status": "success",
            "message": f"模拟{'买入' if trade_type=='BUY' else '卖出'}成功！成交 {shares} 股 @ ¥{price:.2f}",
            "trade": {
                "type": trade_type,
                "shares": shares,
                "price": price,
                "gross_amount": round(gross_amount, 2),
                "fee": round(fee, 2),
                "pnl": round(pnl, 2)
            }
        }
    except Exception as e:
        conn.close()
        return {"status": "error", "message": str(e)}

def reset_sim_account(initial_cash: float = 100000.0) -> Dict[str, Any]:
    """一键重置模拟交易账户到初始状态"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE sim_account SET cash = ?, initial_cash = ?, updated_at = datetime('now', 'localtime') WHERE id = 1", (initial_cash, initial_cash))
    cursor.execute("DELETE FROM sim_position")
    cursor.execute("DELETE FROM sim_trades")
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"模拟交易账户已重置，初始可用现金: ¥{initial_cash:,.2f}"}

def set_initial_position(symbol: str = "sh600036", shares: int = 1000, price: float = 42.0, buy_date: str = "2026-10-28 14:30:00", initial_cash: float = 100000.0) -> Dict[str, Any]:
    """设定初始底仓（如昨天买入 1000 股 @ 42 元）"""
    conn = get_connection()
    cursor = conn.cursor()

    amount = shares * price
    fee = max(5.0, amount * 0.00025)
    remaining_cash = initial_cash - amount - fee

    # 清空重置
    cursor.execute("UPDATE sim_account SET cash = ?, initial_cash = ?, updated_at = datetime('now', 'localtime') WHERE id = 1", (remaining_cash, initial_cash))
    cursor.execute("DELETE FROM sim_position")
    cursor.execute("DELETE FROM sim_trades")

    # 写入初始持仓
    cursor.execute("""
    INSERT INTO sim_position (symbol, shares, avg_cost, updated_at) 
    VALUES (?, ?, ?, ?)
    """, (symbol, shares, price, buy_date))

    # 写入昨日建仓流水记录
    cursor.execute("""
    INSERT INTO sim_trades (symbol, type, shares, price, amount, fee, pnl, created_at, note)
    VALUES (?, 'BUY', ?, ?, ?, ?, 0.0, ?, ?)
    """, (symbol, shares, price, amount, fee, buy_date, "初始底仓 (昨日42元建仓1000股)"))

    conn.commit()
    conn.close()
    return {
        "status": "success",
        "message": f"成功设定初始底仓：{shares} 股 @ ¥{price:.2f} (建仓时间: {buy_date})",
        "shares": shares,
        "price": price,
        "cash": round(remaining_cash, 2)
    }

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
    print("Setting initial position: 1000 shares @ 42.0")
    print(set_initial_position("sh600036", 1000, 42.0, "2026-10-28 14:30:00"))
    print("Sim account summary:", get_sim_account_summary(42.92))

