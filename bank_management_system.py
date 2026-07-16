import sqlite3
import hashlib
import os
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass
from decimal import Decimal
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Account:
    """Account data class"""
    account_number: str
    holder_name: str
    balance: Decimal
    created_at: datetime
    pin_hash: str

class DatabaseManager:
    """Handles all database operations"""
    
    def __init__(self, db_path: str = "bank.db"):
        self.db_path = db_path
        self._initialize_database()
    
    def _initialize_database(self):
        """Create tables if they don't exist"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Accounts table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS accounts (
                        account_number TEXT PRIMARY KEY,
                        holder_name TEXT NOT NULL,
                        balance REAL DEFAULT 0.0,
                        pin_hash TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Transactions table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        account_number TEXT,
                        type TEXT NOT NULL,
                        amount REAL NOT NULL,
                        description TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (account_number) REFERENCES accounts(account_number)
                    )
                ''')
                
                conn.commit()
                logger.info("Database initialized successfully")
                
        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            raise
    
    def execute_query(self, query: str, params: tuple = ()) -> List[tuple]:
        """Execute a query and return results"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                return cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"Query execution error: {e}")
            raise

class AccountManager:
    """Manages account operations"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def create_account(self, holder_name: str, pin: str) -> str:
        """Create a new bank account"""
        account_number = self._generate_account_number()
        pin_hash = self._hash_pin(pin)
        
        query = """
            INSERT INTO accounts (account_number, holder_name, pin_hash)
            VALUES (?, ?, ?)
        """
        
        try:
            self.db.execute_query(query, (account_number, holder_name, pin_hash))
            logger.info(f"Account created: {account_number} for {holder_name}")
            return account_number
        except sqlite3.IntegrityError:
            logger.error(f"Account creation failed for {holder_name}")
            raise ValueError("Account creation failed")
    
    def _generate_account_number(self) -> str:
        """Generate a unique account number"""
        import random
        return f"ACC{random.randint(100000, 999999)}"
    
    def _hash_pin(self, pin: str) -> str:
        """Hash PIN using SHA-256"""
        return hashlib.sha256(pin.encode()).hexdigest()
    
    def verify_pin(self, account_number: str, pin: str) -> bool:
        """Verify account PIN"""
        query = "SELECT pin_hash FROM accounts WHERE account_number = ?"
        result = self.db.execute_query(query, (account_number,))
        
        if not result:
            return False
        
        stored_hash = result[0][0]
        return stored_hash == self._hash_pin(pin)
    
    def get_account(self, account_number: str) -> Optional[Account]:
        """Get account details"""
        query = """
            SELECT account_number, holder_name, balance, created_at, pin_hash
            FROM accounts WHERE account_number = ?
        """
        result = self.db.execute_query(query, (account_number,))
        
        if not result:
            return None
        
        return Account(
            account_number=result[0][0],
            holder_name=result[0][1],
            balance=Decimal(str(result[0][2])),
            created_at=datetime.strptime(result[0][3], '%Y-%m-%d %H:%M:%S'),
            pin_hash=result[0][4]
        )

class TransactionManager:
    """Handles all transaction operations"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.account_manager = AccountManager(db)
    
    def deposit(self, account_number: str, amount: float, description: str = "Deposit") -> bool:
        """Deposit money into account"""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        
        try:
            # Update balance
            query = """
                UPDATE accounts 
                SET balance = balance + ? 
                WHERE account_number = ?
            """
            self.db.execute_query(query, (amount, account_number))
            
            # Record transaction
            query = """
                INSERT INTO transactions (account_number, type, amount, description)
                VALUES (?, ?, ?, ?)
            """
            self.db.execute_query(query, (account_number, 'deposit', amount, description))
            
            logger.info(f"Deposited {amount} to account {account_number}")
            return True
            
        except Exception as e:
            logger.error(f"Deposit failed: {e}")
            return False
    
    def withdraw(self, account_number: str, amount: float, pin: str, 
                 description: str = "Withdrawal") -> bool:
        """Withdraw money from account"""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        
        # Verify PIN
        if not self.account_manager.verify_pin(account_number, pin):
            raise ValueError("Invalid PIN")
        
        # Check balance
        account = self.account_manager.get_account(account_number)
        if not account:
            raise ValueError("Account not found")
        
        if account.balance < Decimal(str(amount)):
            raise ValueError("Insufficient balance")
        
        try:
            # Update balance
            query = """
                UPDATE accounts 
                SET balance = balance - ? 
                WHERE account_number = ?
            """
            self.db.execute_query(query, (amount, account_number))
            
            # Record transaction
            query = """
                INSERT INTO transactions (account_number, type, amount, description)
                VALUES (?, ?, ?, ?)
            """
            self.db.execute_query(query, (account_number, 'withdrawal', amount, description))
            
            logger.info(f"Withdrew {amount} from account {account_number}")
            return True
            
        except Exception as e:
            logger.error(f"Withdrawal failed: {e}")
            return False
    
    def transfer(self, from_account: str, to_account: str, amount: float, 
                 pin: str, description: str = "Transfer") -> bool:
        """Transfer money between accounts"""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        
        if from_account == to_account:
            raise ValueError("Cannot transfer to same account")
        
        # Verify PIN
        if not self.account_manager.verify_pin(from_account, pin):
            raise ValueError("Invalid PIN")
        
        # Check balance
        account = self.account_manager.get_account(from_account)
        if not account:
            raise ValueError("Source account not found")
        
        if account.balance < Decimal(str(amount)):
            raise ValueError("Insufficient balance")
        
        # Check destination account
        dest_account = self.account_manager.get_account(to_account)
        if not dest_account:
            raise ValueError("Destination account not found")
        
        try:
            # Withdraw from source
            query = """
                UPDATE accounts 
                SET balance = balance - ? 
                WHERE account_number = ?
            """
            self.db.execute_query(query, (amount, from_account))
            
            # Deposit to destination
            query = """
                UPDATE accounts 
                SET balance = balance + ? 
                WHERE account_number = ?
            """
            self.db.execute_query(query, (amount, to_account))
            
            # Record transactions
            query = """
                INSERT INTO transactions (account_number, type, amount, description)
                VALUES (?, ?, ?, ?)
            """
            self.db.execute_query(query, (from_account, 'transfer_out', amount, 
                                         f"Transfer to {to_account}"))
            self.db.execute_query(query, (to_account, 'transfer_in', amount, 
                                         f"Transfer from {from_account}"))
            
            logger.info(f"Transferred {amount} from {from_account} to {to_account}")
            return True
            
        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            return False
    
    def get_transaction_history(self, account_number: str, limit: int = 50) -> List[Dict]:
        """Get transaction history for an account"""
        query = """
            SELECT type, amount, description, timestamp
            FROM transactions
            WHERE account_number = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """
        results = self.db.execute_query(query, (account_number, limit))
        
        return [
            {
                'type': r[0],
                'amount': r[1],
                'description': r[2],
                'timestamp': r[3]
            }
            for r in results
        ]

class BankCLI:
    """Command Line Interface for Bank Management System"""
    
    def __init__(self):
        self.db = DatabaseManager()
        self.account_manager = AccountManager(self.db)
        self.transaction_manager = TransactionManager(self.db)
    
    def run(self):
        """Main application loop"""
        print("=" * 50)
        print("WELCOME TO BANK MANAGEMENT SYSTEM")
        print("=" * 50)
        
        while True:
            self._show_main_menu()
            choice = input("\nEnter your choice: ").strip()
            
            if choice == '1':
                self._create_account()
            elif choice == '2':
                self._deposit()
            elif choice == '3':
                self._withdraw()
            elif choice == '4':
                self._transfer()
            elif choice == '5':
                self._view_balance()
            elif choice == '6':
                self._view_transactions()
            elif choice == '7':
                print("\nThank you for using Bank Management System!")
                break
            else:
                print("\nInvalid choice. Please try again.")
    
    def _show_main_menu(self):
        """Display main menu"""
        print("\n" + "-" * 50)
        print("MAIN MENU")
        print("-" * 50)
        print("1. Create Account")
        print("2. Deposit Money")
        print("3. Withdraw Money")
        print("4. Transfer Money")
        print("5. View Balance")
        print("6. View Transaction History")
        print("7. Exit")
    
    def _create_account(self):
        """Create a new account"""
        print("\n" + "-" * 50)
        print("CREATE NEW ACCOUNT")
        print("-" * 50)
        
        name = input("Enter account holder name: ").strip()
        if not name:
            print("Name cannot be empty")
            return
        
        pin = input("Enter 4-digit PIN: ").strip()
        if not pin.isdigit() or len(pin) != 4:
            print("PIN must be 4 digits")
            return
        
        try:
            account_number = self.account_manager.create_account(name, pin)
            print(f"\nAccount created successfully!")
            print(f"Account Number: {account_number}")
            print("Please remember your PIN for future transactions")
        except Exception as e:
            print(f"\nAccount creation failed: {e}")
    
    def _deposit(self):
        """Deposit money"""
        print("\n" + "-" * 50)
        print("DEPOSIT MONEY")
        print("-" * 50)
        
        account = input("Enter account number: ").strip()
        if not account:
            print("Account number cannot be empty")
            return
        
        try:
            amount = float(input("Enter amount to deposit: "))
            if amount <= 0:
                print("Amount must be positive")
                return
        except ValueError:
            print("Invalid amount")
            return
        
        description = input("Enter description (optional): ").strip() or "Deposit"
        
        if self.transaction_manager.deposit(account, amount, description):
            print(f"\nDeposited ₹{amount:.2f} successfully!")
        else:
            print("\nDeposit failed. Please try again.")
    
    def _withdraw(self):
        """Withdraw money"""
        print("\n" + "-" * 50)
        print("WITHDRAW MONEY")
        print("-" * 50)
        
        account = input("Enter account number: ").strip()
        if not account:
            print("Account number cannot be empty")
            return
        
        pin = input("Enter PIN: ").strip()
        if not pin:
            print("PIN cannot be empty")
            return
        
        try:
            amount = float(input("Enter amount to withdraw: "))
            if amount <= 0:
                print("Amount must be positive")
                return
        except ValueError:
            print("Invalid amount")
            return
        
        try:
            if self.transaction_manager.withdraw(account, amount, pin):
                print(f"\nWithdrew ₹{amount:.2f} successfully!")
            else:
                print("\nWithdrawal failed. Please try again.")
        except ValueError as e:
            print(f"\n {e}")
    
    def _transfer(self):
        """Transfer money between accounts"""
        print("\n" + "-" * 50)
        print("TRANSFER MONEY")
        print("-" * 50)
        
        from_account = input("Enter your account number: ").strip()
        if not from_account:
            print("Account number cannot be empty")
            return
        
        pin = input("Enter your PIN: ").strip()
        if not pin:
            print("PIN cannot be empty")
            return
        
        to_account = input("Enter destination account number: ").strip()
        if not to_account:
            print("Destination account number cannot be empty")
            return
        
        try:
            amount = float(input("Enter amount to transfer: "))
            if amount <= 0:
                print("Amount must be positive")
                return
        except ValueError:
            print("Invalid amount")
            return
        
        description = input("Enter description (optional): ").strip() or "Transfer"
        
        try:
            if self.transaction_manager.transfer(from_account, to_account, amount, pin, description):
                print(f"\nTransferred ₹{amount:.2f} successfully!")
            else:
                print("\nTransfer failed. Please try again.")
        except ValueError as e:
            print(f"\n{e}")
    
    def _view_balance(self):
        """View account balance"""
        print("\n" + "-" * 50)
        print("VIEW BALANCE")
        print("-" * 50)
        
        account = input("Enter account number: ").strip()
        if not account:
            print("Account number cannot be empty")
            return
        
        pin = input("Enter PIN: ").strip()
        if not pin:
            print("PIN cannot be empty")
            return
        
        if not self.account_manager.verify_pin(account, pin):
            print("\nInvalid PIN or account not found")
            return
        
        account_data = self.account_manager.get_account(account)
        if account_data:
            print("\n" + "-" * 50)
            print(f"Account Number: {account_data.account_number}")
            print(f"Account Holder: {account_data.holder_name}")
            print(f"Balance: ₹{account_data.balance:.2f}")
            print("-" * 50)
        else:
            print("\nAccount not found")
    
    def _view_transactions(self):
        """View transaction history"""
        print("\n" + "-" * 50)
        print("VIEW TRANSACTION HISTORY")
        print("-" * 50)
        
        account = input("Enter account number: ").strip()
        if not account:
            print("Account number cannot be empty")
            return
        
        pin = input("Enter PIN: ").strip()
        if not pin:
            print("PIN cannot be empty")
            return
        
        if not self.account_manager.verify_pin(account, pin):
            print("\nInvalid PIN or account not found")
            return
        
        try:
            limit = int(input("Enter number of transactions to show (default: 20): ") or 20)
        except ValueError:
            limit = 20
        
        transactions = self.transaction_manager.get_transaction_history(account, limit)
        
        if not transactions:
            print("\nNo transactions found")
            return
        
        print("\n" + "-" * 50)
        print("TRANSACTION HISTORY")
        print("-" * 50)
        print(f"{'Type':<12} {'Amount':<12} {'Description':<25} {'Timestamp'}")
        print("-" * 70)
        
        for t in transactions:
            print(f"{t['type']:<12} ₹{t['amount']:<10.2f} {t['description']:<25} {t['timestamp'][:16]}")
        print("-" * 70)

if __name__ == "__main__":
    cli = BankCLI()
    cli.run()